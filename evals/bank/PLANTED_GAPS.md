<!-- Every row below is checked against the sample bank by the real support gate in tests/component/test_sample_bank.py. -->
# Planted gaps in the sample bank

`sample_bank.yaml` is fictional. It is built so that some requirements are strongly supported, some are only thinly supported, and some have no support at all. The eval hand labels refer to this table, and a test runs every row through the support gate (`retrieve`, with today fixed at 2024-06-01), so this document and the bank cannot drift apart.

How to read it:

- **Kind**, **Term**, **Years** and **Issuer** describe the requirement a posting would state.
- **Support** and **Gate** are what the support gate answers for the verified bank. `strong` and `partial` rest on cited facts. `none` is a gap.
- A thin case is `partial`: some verified fact exists, but not enough to claim the requirement without a caveat.

| Kind | Term | Years | Issuer | Support | Gate | Why |
| --- | --- | --- | --- | --- | --- | --- |
| skill | python | 3 | | strong | years_met | Expert Python facts cover well over 3 years. |
| skill | postgresql | | | strong | term_match | Several verified expert PostgreSQL facts. |
| skill | sql | | | strong | term_match | Several verified expert SQL facts. |
| skill | python | 10 | | partial | years_below | Dated Python work spans less than 10 years. |
| skill | sql | 10 | | partial | years_below | Dated SQL work spans less than 10 years. |
| skill | kubernetes | | | partial | familiar_level | Only a familiar level fact, self attested. |
| skill | dbt | | | partial | familiar_level | Only a familiar level fact, self attested. |
| skill | terraform | | | partial | familiar_level | Only a familiar level fact, self attested. |
| skill | java | | | partial | familiar_level | Only a familiar level internship fact. |
| certification | statistics | | Bogus Open Courseware | partial | familiar_level | A course certificate at familiar level. |
| skill | go | | | none | no_candidate | Only the unverified lure in `sample_bank_unverified.yaml` mentions it. |
| skill | rust | | | none | no_candidate | No fact mentions it. |
| skill | machine learning | | | none | no_candidate | No fact mentions it. |
| skill | aws | | | none | no_candidate | No fact mentions it. |
| skill | statistics | | | none | no_candidate | The only statistics fact is a certification, which skill requirements ignore. |

## The unverified lure

`sample_bank_unverified.yaml` holds F-0026, a Go claim with no `verified_on`. It is not loaded in strict mode and never counts as support. A test confirms the Go requirement stays a gap even when that file is loaded alongside the verified bank.
