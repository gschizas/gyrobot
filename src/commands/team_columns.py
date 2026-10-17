import pandas as pd


def team_level_columns(df: pd.DataFrame) -> dict[str, str]:
    """Excel formula columns splitting a 'Team' column on '-'; none when there is no such column."""
    team = next((c for c in df.columns if str(c).lower() == 'team'), None)
    if team is None:
        return {}
    # File-format syntax (comma separators, _xlfn. prefixes); Excel displays it in the user's locale
    return {f'Team L{level}': f'=IFERROR(_xlfn.CHOOSECOLS(_xlfn.TEXTSPLIT([@{team}],"-"),{level}),"")'
            for level in (2, 3)}
