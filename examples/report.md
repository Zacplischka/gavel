# gavel evaluation report

## Overall

- **Items:** 24
- **Pass:** 16
- **Fail:** 7
- **Manual review (verdict -1):** 1
- **Accuracy (judged items only):** 69.6%
- **Strict accuracy (review counts against):** 66.7%

## By tier

| Tier | Items | Pass | Fail | Review | Accuracy |
|------|------:|-----:|-----:|-------:|---------:|
| basic | 6 | 5 | 1 | 0 | 83.3% |
| easy | 6 | 3 | 3 | 0 | 50.0% |
| medium | 6 | 4 | 2 | 0 | 66.7% |
| hard | 6 | 4 | 1 | 1 | 80.0% |

## Failures

### `b5` (basic)

**Question:** How many employees does the company have?

**Agent SQL:** `SELEC COUNT(*) FROM Employee`

**Rationale:** agent SQL failed to execute: near "SELEC": syntax error

### `e3` (easy)

**Question:** What is the total revenue across all invoices?

**Agent SQL:** `SELECT ROUND(SUM(Total), 2) FROM Invoice WHERE Total > 0.99`

**Rationale:** result table does not match gold; answer prose looks right (similarity=0.95) but table data is authoritative over prose -> fail

### `e4` (easy)

**Question:** How many distinct billing countries appear on invoices?

**Agent SQL:** `SELECT COUNT(BillingCountry) FROM Invoice`

**Rationale:** result table does not match gold

### `e6` (easy)

**Question:** How many albums does the artist Iron Maiden have?

**Agent SQL:** `SELECT COUNT(*) FROM Album a JOIN Artist ar ON a.ArtistId = ar.ArtistId WHERE ar.Name = 'iron maiden'`

**Rationale:** result table does not match gold; answer prose looks right (similarity=0.95) but table data is authoritative over prose -> fail

### `m3` (medium)

**Question:** Which 3 artists have the most tracks? Return artist name and track count, highest first.

**Agent SQL:** `SELECT ar.Name, COUNT(*) AS Tracks FROM Album al JOIN Artist ar ON al.ArtistId = ar.ArtistId GROUP BY ar.ArtistId ORDER BY Tracks DESC, ar.Name LIMIT 3`

**Rationale:** result table does not match gold (row order enforced; gold has top-level ORDER BY)

### `m5` (medium)

**Question:** What are the 4 highest invoice totals? Return invoice id and total, highest first.

**Agent SQL:** `SELECT InvoiceId, Total FROM Invoice ORDER BY Total ASC, InvoiceId LIMIT 4`

**Rationale:** result table does not match gold (row order enforced; gold has top-level ORDER BY)

### `h3` (hard)

**Question:** Which artists have more than 10 albums? Return artist name and album count, most albums first.

**Agent SQL:** `SELECT ar.Name, COUNT(*) AS Albums FROM Album al JOIN Artist ar ON al.ArtistId = ar.ArtistId GROUP BY ar.ArtistId HAVING COUNT(*) >= 10 ORDER BY Albums DESC, ar.Name`

**Rationale:** result table does not match gold (row order enforced; gold has top-level ORDER BY)

## Manual-review queue

These items could not be scored automatically (verdict -1). A human
should look at each one — do not fold them into pass or fail.

- `h6` (hard): How many customers spent more than the average customer's lifetime spend?
  - no SQL provided; cannot verify against the database -> manual review

