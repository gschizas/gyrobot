import unittest

from backend.names import names_agree, romanize_greek, split_greek_name, title_case


class NamesTest(unittest.TestCase):
    def test_title_case_handles_dashes_and_apostrophes(self):
        self.assertEqual(title_case('ANNA-MARIA'), 'Anna-Maria')
        self.assertEqual(title_case("  o'BRIEN  van   dyke "), "O'Brien Van Dyke")
        self.assertEqual(title_case(''), '')

    def test_greek_final_sigma(self):
        self.assertTrue(title_case('ΣΧΙΝΑΣ').endswith('ς'))

    def test_split_greek_name(self):
        self.assertEqual(split_greek_name('ΝΙΚΟΛΑΟΣ|ΣΧΙΝΑΣ'), (title_case('ΝΙΚΟΛΑΟΣ'), title_case('ΣΧΙΝΑΣ')))
        self.assertEqual(split_greek_name('ΝΙΚΟΛΑΟΣ'), (title_case('ΝΙΚΟΛΑΟΣ'), ''))
        self.assertEqual(split_greek_name(''), ('', ''))

    def test_romanize_is_title_case(self):
        self.assertEqual(romanize_greek('ΣΧΙΝΑΣ'), 'Schinas')
        self.assertEqual(romanize_greek('ΜΑΡΙΑ-ΕΛΕΝΗ'), 'Maria-Eleni')

    def test_names_agree(self):
        self.assertTrue(names_agree('Schinas', 'ΣΧΙΝΑΣ'))
        self.assertTrue(names_agree('schinas', 'Σχινάς'))
        self.assertFalse(names_agree('Shinas', 'ΣΧΙΝΑΣ'))
        self.assertTrue(names_agree('Whatever', ''))


if __name__ == '__main__':
    unittest.main()
