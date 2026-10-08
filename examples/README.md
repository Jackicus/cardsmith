# Example decks

Ready-to-print decks that pair with the built-in templates. Build any of them
from the repository root. The output folder gets the plate 3MFs and a
`PRINT_GUIDE.md` that lists the filament-change layers.

| Deck | Cards | Template | What you get |
|------|------:|----------|--------------|
| `japanese/jlpt-n5-kanji.tsv` | 80 | `kanji` | Portrait kanji card with on/kun readings, meaning and JLPT tag |
| `japanese/jlpt-n5-kanji.tsv` | 80 | `minimal` | One big kanji on a plain 50 × 50 tile |
| `japanese/n5-vocab-furigana.tsv` | 61 | `vocab-furigana` | Landscape vocab card with furigana above the kanji |
| `other/periodic-table.csv` | 118 | `element` | Periodic-table tile with number, symbol, name and atomic mass |
| `other/spanish-basics.csv` | 40 | `language-pair` | Spanish word, English translation and a word-type tag |

```sh
cardsmith build examples/japanese/jlpt-n5-kanji.tsv     -t kanji          -o out/kanji
cardsmith build examples/japanese/jlpt-n5-kanji.tsv     -t minimal        -o out/kanji-minimal
cardsmith build examples/japanese/n5-vocab-furigana.tsv -t vocab-furigana -o out/vocab
cardsmith build examples/other/periodic-table.csv       -t element        -o out/elements
cardsmith build examples/other/spanish-basics.csv       -t language-pair  -o out/spanish
```

Run `cardsmith check <deck> -t <template>` first to see layout and
printability warnings. Add `--limit 6` to print a small test batch.

All templates use **Noto Sans CJK JP** (Bold and Black weights). It covers
Japanese and Latin text, accented letters included. Run `cardsmith fonts --ja`
to see whether you have it installed.

## Data notes

- **Kanji readings**: on'yomi are in katakana and kun'yomi in hiragana, with
  okurigana in brackets, e.g. `ショク / た(べる)`. Each card shows only the
  most common readings so the line fits on the card.
- **Furigana**: the `furigana` column uses Anki syntax. Put a space before each
  kanji block that follows other text, e.g. `食[た]べ 物[もの]` or `お 茶[ちゃ]`.
  Kana-only words need no brackets.
- **Atomic masses**: these are IUPAC standard atomic weights, abridged. For
  elements with no stable isotopes, the mass number of the longest-lived known
  isotope is shown in brackets, e.g. `[294]`.
