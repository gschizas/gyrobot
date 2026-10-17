import re
from collections.abc import Callable

import pandas as pd


def safe_excel_table_name(name: str) -> str:
    """Excel table names: letters, digits, underscore or dot; must start with a letter or underscore."""
    cleaned = re.sub(r'[^A-Za-z0-9_.]', '_', str(name))
    if not cleaned or not re.match(r'[A-Za-z_]', cleaned):
        cleaned = f'T_{cleaned}'
    return cleaned[:255]


FormulaColumns = Callable[[pd.DataFrame], dict[str, str]]


def write_excel_table(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str, table_name: str | None = None,
                      formula_columns: FormulaColumns | None = None):
    """Write a DataFrame to an xlsxwriter-backed ExcelWriter as a formatted Excel Table with auto-sized columns.

    formula_columns, if given, receives the DataFrame and returns {header: formula} for extra columns
    appended to the table.
    """
    df = df.reset_index(drop=True)
    df.columns = [str(c) for c in df.columns]
    formulas = {name: formula for name, formula in (formula_columns(df) if formula_columns else {}).items()
                if name not in df.columns}
    for name in formulas:
        df[name] = ''
    columns = list(df.columns)
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    worksheet = writer.sheets[sheet_name]
    if not columns:
        return

    # Create an actual Excel Table object over the written range.
    table_last_row = max(1, len(df))
    worksheet.add_table(
        0,
        0,
        table_last_row,
        len(columns) - 1,
        {
            'name': safe_excel_table_name(table_name or sheet_name),
            'columns': [{'header': column, **({'formula': formulas[column]} if column in formulas else {})}
                        for column in columns],
            'style': 'Table Style Medium 9',
        }
    )

    # Auto-size columns for readability.
    for col_index, column in enumerate(columns):
        column_values = [str(v) for v in df.iloc[:, col_index].tolist()] if not df.empty else []
        max_len = max([len(column), *[len(v) for v in column_values]])
        worksheet.set_column(col_index, col_index, min(max_len + 2, 80))
