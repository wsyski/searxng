# Workflows

Worked examples for what this instance is actually used for. Every command here has been run. The
numbers are what came back on **2026-10-11**, and the two that have been re-measured since carry
their own date.

## Has any analyst office written about a name I hold?

The question a small analyst office answers. Sparse by design — empty is the normal answer, and
a hit means a dedicated analyst picked that company.

```bash
sxq orlen -c 'finance poland'
```

Returns SII's *Spółka tygodnia* note on ORLEN, plus a Książak note that mentions ORLEN inside
its body (the company is **not** in that title — WordPress `search` matches body text).

The `finance poland` category fans out to all four Polish engines; SearXNG runs them concurrently
and caches. The engines are in `finance` and `finance poland` only, so a default general/news query
does not reach them.

For a Swedish name use `-c 'finance sweden'` (`aktienyheterna`, `placera`), which the Avanza books
ask for the same way. `-c finance` is the union of both markets and is the right ask when the
question names no market.

```bash
sxq granges -c 'finance sweden'
```

Both Swedish engines filter the site's own fuzzy matching: a row is kept only when every query
term appears as a whole word in what the engine can see of it. So an empty answer from
`finance sweden` means "nobody wrote about this name", not "the engine is broken" — check
`engine_data.<name>.site_rows` to tell the two apart.

**Check `.unresponsive_engines` before recording "no coverage".** All three are rate-limited or
blocking-prone: `sii` returns HTTP 429 after two or three queries in a burst and suspends for
an hour. A coverage report that reads a throttled engine as silence is worse than no report.

## Recent news about a company

```bash
sxq kghm -c news
```

`sii` is **not** in `news` any more; it runs only in `finance`. For company coverage use
`sxq kghm -c 'finance poland'`. A `sii` row always carries every query term in its title or teaser, so a
hit there names its company.

`stooq` is **not** in `news`; it is in `finance` only, because its site disallows crawling.
`sxq kghm -c 'finance poland'` includes it, and so does the portfolio's daily finance request; a manual
call is explicit, so keep those sparse.

**`--time-range` works on a news query now** (as of 2026-10-15; this paragraph used to say the
opposite). `-c news --time-range week` used to return zero with an empty
`.unresponsive_engines`, because every engine in the category lacks `time_range_support` and
SearXNG *drops* those when a range is set — so no engine ran at all. `bing news` is now enabled
and does support ranges, and `-c news --time-range week` answers with `bing news` rows. One
caveat worth keeping: if the result is ever empty again `sxq` says why on stderr. `-c general --time-range week` works too;
otherwise filter on `publishedDate` yourself.

## Code, issues and PRs

The `github` engine finds **repositories**, and does not search code:

| Want | Use |
|---|---|
| Find a repository | `sxq "react hooks" -e github` |
| Find text inside code | `gh api -X GET search/code -f q='<term>'` |
| Issues and PRs | `gh issue list` / `gh pr list`, per repo |
| GitHub URLs in web results | `sxq "site:github.com <terms>" -c general` |

Quote multi-word queries. `sxq react hooks` is two arguments and the second is rejected.

`gitlab`, `codeberg`, `gitea.com` and `sourcehut` are all **disabled** here, so a category query
never reaches them. `categories.md` still lists `gitlab` under engines observed failing — that is a
2026-10-11 observation from before it was switched off, not something you can reproduce. For code
that is not on GitHub, check the engine's state in `/config` before assuming it was tried.

## A macro question, not a company

```bash
sxq "AI regulation" -c news
```

Finds a Dino Polska note at Książak, because inflation drives that thesis. Thematic queries
work even though the term is not a company, ticker or ISIN — a coverage sweep keyed only on
ticker will never surface these.

## Prices and quotes

Not a search problem. Scrape a quote page with firecrawl, or use a market-data API. Snippets
carry no price.

## Package or library research

```bash
sxq pydantic -c packages        # pypi, npm, pkg.go.dev, lib.rs, hoogle, docker hub
sxq "pytest fixtures" -c it    # 17 enabled engines, 151 results (2026-10-15; was 148)
```

`metacpan` was failing in the sample run; the category still answers.

## When results look wrong

```bash
sxq --health                     # is the instance up, how many engines, how many categories
sxq test -e <engine> -n 1        # one engine, pinned
sxq "<term>" -c general --json | jq '.unresponsive_engines'
```

Order of suspicion:

1. **`.unresponsive_engines` non-empty** — blocked or throttled, not "nothing exists".
2. **A long list across many engines** — the instance or network is down. `sxq --health`.
3. **One engine named repeatedly** — pin it and confirm before blaming it; `yahoo` failed once
   and then worked 3/3.
4. **Category returns zero but has engines** — see `references/categories.md`.
