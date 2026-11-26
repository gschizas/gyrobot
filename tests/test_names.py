import unittest

from backend.names import names_agree, romanize_greek, split_greek_name, title_case


class NamesTest(unittest.TestCase):
    def test_title_case_handles_dashes_and_apostrophes(self):
        self.assertEqual(title_case('ANNA-MARIA'), 'Anna-Maria')
        self.assertEqual(title_case("  o'BRIEN  van   dyke "), "O'Brien Van Dyke")
        self.assertEqual(title_case(''), '')

    def test_greek_final_sigma(self):
        self.assertTrue(title_case('ΣΧΙΖΑΣ').endswith('ς'))

    def test_split_greek_name(self):
        self.assertEqual(split_greek_name('ΓΙΩΡΓΟΣ|ΣΧΙΖΑΣ'), (title_case('ΓΙΩΡΓΟΣ'), title_case('ΣΧΙΖΑΣ')))
        self.assertEqual(split_greek_name('ΓΙΩΡΓΟΣ'), (title_case('ΓΙΩΡΓΟΣ'), ''))
        self.assertEqual(split_greek_name(''), ('', ''))

    def test_romanize_is_title_case(self):
        self.assertEqual(romanize_greek('ΣΧΙΖΑΣ'), 'Schizas')
        self.assertEqual(romanize_greek('ΜΑΡΙΑ-ΕΛΕΝΗ'), 'Maria-Eleni')

    def test_names_agree(self):
        self.assertTrue(names_agree('Schizas', 'ΣΧΙΖΑΣ'))
        self.assertTrue(names_agree('schizas', 'Σχίζας'))
        self.assertFalse(names_agree('Shizas', 'ΣΧΙΖΑΣ'))
        self.assertTrue(names_agree('Whatever', ''))


if __name__ == '__main__':
    unittest.main()
