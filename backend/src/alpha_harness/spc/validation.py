"""Pure checks for an SPC submission. Standard library only, so they run anywhere and test fast.

Sources: BRAIN's "What do I need to submit?" article (fields, output format, limits), its
"What can my prompt cover?" and "What is a prompt?" FAQs, and the community guides on the
failure modes that silently cost PnL (made-up ISINs, over-long or over-short books, output that
changes from run to run). A rule that only a community guide states is a warning, never an error.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

Level = Literal["error", "warning", "info"]

#: The models the submission form accepts, as BRAIN lists them.
MODELS = (
    "Claude",
    "GPT",
    "Gemini",
    "DeepSeek",
    "Kimi",
    "Qwen3",
    "GLM",
    "Llama",
    "Minimax",
    "Mistral",
)
FREQUENCIES = ("Daily", "Weekly", "Monthly", "Quarterly")

PROMPT_MAX_CHARS = 10_000
MODEL_VERSION_MAX_CHARS = 100
#: Community guide: prompt plus sample over BUDGET_MAX_CHARS risks truncated output, and over
#: BUDGET_WARN_CHARS instability.
BUDGET_WARN_CHARS = 24_000
BUDGET_MAX_CHARS = 28_000
#: "~50 equities" is the recommendation; outside this range the guides report degraded output.
BOOK_LOW, BOOK_HIGH, BOOK_TOO_BIG = 40, 60, 80
MAX_ACTIVE_PROMPTS = 50
MAX_PROMPTS_PER_DAY = 50
COVERAGE_TARGET = 500

#: The keys of each entry in the output array.
REQUIRED_KEYS = (
    "company_name",
    "ticker",
    "isin",
    "mic",
    "confidence_score",
    "investment_horizon",
    "return_prediction",
)

ISIN_SHAPE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
MIC_SHAPE = re.compile(r"[A-Z0-9]{4}")

#: Primary exchanges that appear in practice. Not exhaustive: an unlisted MIC that is well
#: formed is a warning to look at, not an error.
KNOWN_MICS = frozenset(
    [
        "XNAS",
        "XNYS",
        "ARCX",
        "XASE",
        "BATS",
        "XTSE",
        "XTSX",
        "XMEX",
        "BVMF",
        "XLON",
        "XPAR",
        "XAMS",
        "XBRU",
        "XLIS",
        "XMIL",
        "XMAD",
        "XSWX",
        "XETR",
        "XFRA",
        "XSTO",
        "XCSE",
        "XHEL",
        "XOSL",
        "XWAR",
        "XWBO",
        "XDUB",
        "XATH",
        "XIST",
        "XTAE",
        "XJSE",
        "XSAU",
        "XTKS",
        "XHKG",
        "XSHG",
        "XSHE",
        "XKRX",
        "XKOS",
        "XTAI",
        "XSES",
        "XBKK",
        "XIDX",
        "XKLS",
        "XASX",
        "XNZE",
        "XNSE",
        "XBOM",
    ]
)


@dataclass(frozen=True, slots=True)
class Issue:
    level: Level
    #: Stable machine-readable code, so the UI and tests do not match on wording.
    code: str
    message: str
    #: Which form field or output row this is about, when one.
    where: str | None = None


@dataclass(slots=True)
class Entry:
    company_name: str
    ticker: str
    isin: str
    mic: str
    confidence_score: float
    investment_horizon: int
    return_prediction: float

    @property
    def key(self) -> str:
        return f"{self.isin}|{self.mic}"


@dataclass(slots=True)
class Book:
    """What parsing a sample output found: the usable rows and every problem with the rest."""

    entries: list[Entry] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def isin_valid(isin: str) -> bool:
    """Shape and check digit (ISO 6166: letters become 10 to 35, then Luhn over every digit)."""
    if not ISIN_SHAPE.fullmatch(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for position, char in enumerate(reversed(digits)):
        n = int(char)
        if position % 2 == 1:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_output(text: str) -> Book:
    """Read a sample output the way the platform does: strict JSON, an array of entries."""
    book = Book()
    add = book.issues.append
    raw = text.strip()
    if not raw:
        add(Issue("error", "output_empty", "The sample output is empty."))
        return book

    if raw.startswith("```"):
        add(
            Issue(
                "error",
                "output_markdown",
                "The output is wrapped in a markdown code fence. The prompt must produce bare "
                "JSON — no fences, no explanation before or after.",
            )
        )
        raw = re.sub(r"^```[A-Za-z]*\s*|\s*```$", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        add(
            Issue(
                "error",
                "output_not_json",
                f"The output is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}). "
                "A single sentence of explanation before or after the array breaks the "
                "whole submission.",
            )
        )
        return book

    if isinstance(data, dict):
        legacy = bool(data) and all(isinstance(k, str) and "|" in k for k in data)
        add(
            Issue(
                "error",
                "output_legacy_map" if legacy else "output_not_array",
                'This is an {"ISIN|MIC": confidence} map, the format an unofficial community '
                "guide describes. BRAIN's submission article asks for an array of objects with "
                + ", ".join(REQUIRED_KEYS)
                + "."
                if legacy
                else "The output must be a JSON array of objects, one per stock.",
            )
        )
        return book
    if not isinstance(data, list):
        add(Issue("error", "output_not_array", "The output must be a JSON array of objects."))
        return book
    if not data:
        add(Issue("error", "output_no_rows", "The array is empty: no positions."))
        return book

    for index, row in enumerate(data, start=1):
        _read_row(book, index, row)
    return book


def _read_row(book: Book, index: int, row: Any) -> None:
    where = f"row {index}"

    def bad(code: str, message: str) -> None:
        book.issues.append(Issue("error", code, f"Row {index}: {message}", where))

    if not isinstance(row, dict):
        bad("row_not_object", "is not an object.")
        return
    missing = [k for k in REQUIRED_KEYS if k not in row]
    if missing:
        bad("row_missing_keys", f"is missing {', '.join(missing)}.")
        return
    extra = sorted(set(row) - set(REQUIRED_KEYS))
    if extra:
        book.issues.append(
            Issue("warning", "row_extra_keys", f"Row {index}: unexpected keys {extra}.", where)
        )

    name, ticker, isin, mic = (row[k] for k in ("company_name", "ticker", "isin", "mic"))
    if not all(isinstance(v, str) and v.strip() for v in (name, ticker, isin, mic)):
        bad("row_text_fields", "company_name, ticker, isin and mic must be non-empty strings.")
        return
    if isin != isin.strip().upper() or mic != mic.strip().upper():
        bad("row_case", f"{isin!r}/{mic!r} must be upper case with no spaces.")
        return
    if not ISIN_SHAPE.fullmatch(isin):
        bad("isin_shape", f"ISIN {isin!r} is not 2 letters, 9 letters or digits and a digit.")
        return
    if not isin_valid(isin):
        bad(
            "isin_checksum",
            f"ISIN {isin} has a wrong check digit, so it is invented or mistyped and the "
            "position would earn nothing.",
        )
        return
    if not MIC_SHAPE.fullmatch(mic):
        bad("mic_shape", f"MIC {mic!r} must be 4 letters or digits (e.g. XNAS).")
        return
    if mic not in KNOWN_MICS:
        book.issues.append(
            Issue(
                "warning",
                "mic_unfamiliar",
                f"Row {index}: MIC {mic} is well formed but not a common primary exchange. "
                "Check that it is where this ISIN actually trades.",
                where,
            )
        )

    conf, horizon, ret = (
        row["confidence_score"],
        row["investment_horizon"],
        row["return_prediction"],
    )
    if not _number(conf) or not -1 <= conf <= 1:
        bad("confidence_range", f"confidence_score {conf!r} must be a number from -1 to 1.")
        return
    if not _number(horizon) or horizon != int(horizon) or horizon <= 0:
        bad(
            "horizon_value",
            f"investment_horizon {horizon!r} must be a positive whole number of days.",
        )
        return
    if not _number(ret) or ret <= 0:
        bad(
            "return_sign",
            f"return_prediction {ret!r} must be a positive number; direction comes from the "
            "sign of confidence_score.",
        )
        return
    if conf == 0:
        book.issues.append(
            Issue(
                "warning",
                "confidence_zero",
                f"Row {index}: confidence_score 0 means no position; it only spends context.",
                where,
            )
        )
    if horizon > 252:
        book.issues.append(
            Issue(
                "warning",
                "horizon_long",
                f"Row {index}: investment_horizon {int(horizon)} is over a trading year.",
                where,
            )
        )
    if ret >= 1:
        book.issues.append(
            Issue(
                "warning",
                "return_large",
                f"Row {index}: return_prediction {ret} is 100% or more. It must be the return "
                "over the same horizon, not an annualised figure.",
                where,
            )
        )
    book.entries.append(Entry(name, ticker, isin, mic, float(conf), int(horizon), float(ret)))


@dataclass(slots=True)
class Stats:
    count: int
    long: int
    short: int
    gross: float
    net: float
    distinct_isins: int
    median_horizon: int | None


def book_stats(entries: list[Entry]) -> Stats:
    horizons = sorted(e.investment_horizon for e in entries)
    return Stats(
        count=len(entries),
        long=sum(e.confidence_score > 0 for e in entries),
        short=sum(e.confidence_score < 0 for e in entries),
        gross=round(sum(abs(e.confidence_score) for e in entries), 6),
        net=round(sum(e.confidence_score for e in entries), 6),
        distinct_isins=len({e.isin for e in entries}),
        median_horizon=horizons[len(horizons) // 2] if horizons else None,
    )


def check_book(entries: list[Entry]) -> list[Issue]:
    """Properties of the whole book rather than one row."""
    out: list[Issue] = []
    if not entries:
        return out
    seen: dict[str, int] = {}
    for e in entries:
        seen[e.key] = seen.get(e.key, 0) + 1
    dupes = sorted(k for k, n in seen.items() if n > 1)
    if dupes:
        out.append(
            Issue(
                "warning",
                "duplicate_positions",
                f"{len(dupes)} instrument(s) appear more than once: {', '.join(dupes[:5])}.",
            )
        )
    n = len(entries)
    if n < BOOK_LOW:
        out.append(
            Issue(
                "warning",
                "book_small",
                f"{n} names. About 50 is recommended: in a small book one bad name is a large "
                "share of the portfolio.",
            )
        )
    elif n > BOOK_TOO_BIG:
        out.append(
            Issue(
                "warning",
                "book_large",
                f"{n} names is more than the model can research properly in one context; "
                "some will be filled from memory. About 50 is recommended.",
            )
        )
    elif n > BOOK_HIGH:
        out.append(
            Issue("info", "book_above_target", f"{n} names; the recommendation is about 50.")
        )
    horizons = {e.investment_horizon for e in entries}
    if n >= 10 and len(horizons) == 1:
        out.append(
            Issue(
                "warning",
                "horizon_uniform",
                f"Every position uses investment_horizon {next(iter(horizons))}. BRAIN asks for a "
                "horizon tied to each thesis, not one default.",
            )
        )
    if all(e.confidence_score > 0 for e in entries) or all(e.confidence_score < 0 for e in entries):
        out.append(Issue("info", "one_sided", "The book is entirely long or entirely short."))
    return out


def check_fields(
    *,
    name: str,
    prompt: str,
    model: str,
    model_version: str,
    frequency: str,
    weight: float,
    sample_chars: int,
) -> list[Issue]:
    """The seven form fields, plus the advisory checks on what the prompt says."""
    out: list[Issue] = []

    def add(level: Level, code: str, message: str, where: str) -> None:
        out.append(Issue(level, code, message, where))

    if not name.strip():
        add("error", "name_empty", "Give the prompt a name.", "name")
    elif len(name) > 100:
        add("warning", "name_long", "The name is long; BRAIN shows it in a list.", "name")

    text = prompt.strip()
    if not text:
        add("error", "prompt_empty", "The prompt is empty.", "prompt")
    if len(prompt) > PROMPT_MAX_CHARS:
        add(
            "error",
            "prompt_too_long",
            f"The prompt is {len(prompt):,} characters; the limit is {PROMPT_MAX_CHARS:,}.",
            "prompt",
        )
    total = len(prompt) + sample_chars
    if total > BUDGET_MAX_CHARS:
        add(
            "warning",
            "budget_over",
            f"Prompt plus sample is {total:,} characters. A community guide reports failed "
            f"output above {BUDGET_MAX_CHARS:,}.",
            "prompt",
        )
    elif total > BUDGET_WARN_CHARS:
        add(
            "warning",
            "budget_high",
            f"Prompt plus sample is {total:,} characters; a community guide reports instability "
            f"above {BUDGET_WARN_CHARS:,}.",
            "prompt",
        )

    if model.strip().lower() not in {m.lower() for m in MODELS}:
        add("error", "model_unknown", f"Model must be one of {', '.join(MODELS)}.", "model")
    if len(model_version) > MODEL_VERSION_MAX_CHARS:
        add(
            "error",
            "model_version_long",
            f"Model version is over {MODEL_VERSION_MAX_CHARS} characters.",
            "modelVersion",
        )
    elif re.search(r"[/:]", model_version) or re.search(r"\d{4}-\d{2}", model_version):
        add(
            "warning",
            "model_version_proxy",
            "This looks like a router's compound name (e.g. openai/gpt-5.5-2026-06). Copy the "
            "version from the model provider's own site.",
            "modelVersion",
        )
    if frequency not in FREQUENCIES:
        add(
            "error",
            "frequency_unknown",
            f"Update frequency must be one of {', '.join(FREQUENCIES)}.",
            "frequency",
        )
    elif frequency == "Quarterly":
        add(
            "info",
            "frequency_quarterly",
            "A Quarterly prompt keeps running into the next quarter until its weight is set to 0.",
            "frequency",
        )

    if not _number(weight) or not 0 <= weight <= 1:
        add("error", "weight_range", "Weight must be between 0 and 1.", "weight")
    else:
        if round(weight, 2) != weight:
            add("error", "weight_decimals", "Weight takes at most 2 decimal places.", "weight")
        if weight == 0:
            add("info", "weight_zero", "A weight of 0 means this prompt does not run.", "weight")

    lowered = text.lower()
    advice = (
        (
            "temperature" not in lowered,
            "advice_temperature",
            "The prompt never mentions temperature. BRAIN asks for the lowest temperature or "
            "equivalent reproducibility setting to be requested in the prompt.",
        ),
        (
            not re.search(r"web[ -]?search|search the web|browse|verify.*source", lowered),
            "advice_search",
            "The prompt does not tell the model to search the web and verify sources, so the "
            "result may rest on stale recall.",
        ),
        (
            "json" not in lowered,
            "advice_json",
            "The prompt never asks for JSON, which is the only output the platform accepts.",
        ),
        (
            not re.search(
                r"\b\d{2,3}\b\s*(?:[-\u2013]\s*\d{2,3}\s*)?(?:\w+\s){0,3}"
                r"(?:stocks|equities|names|companies|tickers|positions|isins)",
                lowered,
            )
            and not re.search(r"(?:exactly|about|around|~|approximately)\s*\d{2,3}", lowered),
            "advice_count",
            "The prompt states no explicit number of names. Without one the model may return "
            "far fewer than intended.",
        ),
        (
            "isin" not in lowered or "mic" not in lowered,
            "advice_identifiers",
            "The prompt does not mention ISIN and MIC. Ask for official 12-character ISINs with "
            "the primary exchange's MIC, and for unsure names to be left out.",
        ),
        (
            bool(
                re.search(
                    r"\[[^\]\n]*(?:your|insert|\.\.\.|total)[^\]\n]*\]|<placeholder>|lorem", lowered
                )
            ),
            "placeholder_left",
            "The prompt still contains template placeholder text.",
        ),
    )
    for flagged, code, message in advice:
        if flagged and text:
            out.append(
                Issue("error" if code == "placeholder_left" else "warning", code, message, "prompt")
            )
    return out


@dataclass(slots=True)
class Stability:
    runs: int
    identical: bool
    #: Smallest overlap of any run's instruments with the first run's, 0 to 1.
    min_overlap: float
    #: Largest change in one instrument's confidence between a run and the first.
    max_confidence_shift: float
    #: Instruments present in some runs but not all.
    unstable_names: list[str]


def compare_runs(books: list[Book]) -> tuple[Stability | None, list[Issue]]:
    """Whether the same prompt produced the same book each time. Needs two parsed runs."""
    usable = [b for b in books if b.entries and not any(i.level == "error" for i in b.issues)]
    issues: list[Issue] = []
    if len(books) > len(usable):
        issues.append(
            Issue(
                "error",
                "run_invalid",
                f"{len(books) - len(usable)} of {len(books)} runs did not parse as valid output, "
                "so the prompt is not reliably producing it.",
            )
        )
    if len(usable) < 2:
        return None, issues

    first = {e.key: e.confidence_score for e in usable[0].entries}
    overlaps, shifts = [], []
    everywhere = set(first)
    anywhere = set(first)
    for book in usable[1:]:
        other = {e.key: e.confidence_score for e in book.entries}
        union = set(first) | set(other)
        overlaps.append(len(set(first) & set(other)) / len(union))
        shifts.extend(abs(first[k] - other[k]) for k in set(first) & set(other))
        everywhere &= set(other)
        anywhere |= set(other)
    canon = [
        sorted(
            (e.key, e.confidence_score, e.investment_horizon, e.return_prediction)
            for e in b.entries
        )
        for b in usable
    ]
    identical = all(c == canon[0] for c in canon[1:])
    stability = Stability(
        runs=len(usable),
        identical=identical,
        min_overlap=round(min(overlaps), 4),
        max_confidence_shift=round(max(shifts, default=0.0), 6),
        unstable_names=sorted(anywhere - everywhere),
    )
    if identical:
        issues.append(Issue("info", "runs_identical", f"{len(usable)} runs are identical."))
    else:
        issues.append(
            Issue(
                "warning",
                "runs_differ",
                f"The {len(usable)} runs differ: the smallest overlap is "
                f"{stability.min_overlap:.0%} "
                f"and a confidence moved by up to {stability.max_confidence_shift:g}. A prompt "
                "that varies between runs can be marked unstable. Lower the temperature, "
                "fix the universe, and state an explicit count.",
            )
        )
    return stability, issues


def overlap(a: set[str], b: set[str]) -> float:
    """Share of the union two prompts have in common, by ISIN."""
    return len(a & b) / len(a | b) if a | b else 0.0
