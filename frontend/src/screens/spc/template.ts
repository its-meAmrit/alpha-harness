/**
 * A starting prompt built from BRAIN's own guidance: a role, one task, an explicit count,
 * web search with verification, identifiers it must not invent, the lowest temperature, and
 * the exact output. The bracketed lines are placeholders; the screen refuses to call the
 * prompt ready until they are replaced.
 */

export const PROMPT_TEMPLATE = `You are [YOUR ROLE, e.g. a forensic accountant specialising in cash-flow quality].

TASK
Search the web for current data and verify every source. Build a long/short book of about 50 listed global equities for this thesis:
[YOUR THESIS: why the market misprices this signal, and how long the drift should last]

SCREEN
1. [STEP ONE: the liquid universe to screen]
2. [STEP TWO: the signal]
3. [STEP THREE: how to rank, and which names go short]

RULES
- Return exactly 50 stocks. Only liquid, primary listings; no OTC.
- Give each stock its official 12-character ISIN and the 4-letter MIC of its primary exchange (for example XNAS, XNYS, XLON, XETR). If you are not certain of an identifier, leave that stock out. Never invent one and never explain.
- confidence_score runs from -1 to 1: positive is long, negative is short.
- investment_horizon is the number of trading days until this stock's thesis should play out, tied to a concrete event or comparable move. Do not reuse one default number.
- return_prediction is the positive expected return over that same horizon, not annualised. The sign of confidence_score gives the direction.
- Use the lowest temperature or equivalent reproducibility setting, so the output is the same on every run.

OUTPUT
Output only valid JSON, with no markdown and no text before or after, as an array:
[{"company_name": "Apple Inc.", "ticker": "AAPL", "isin": "US0378331005", "mic": "XNAS", "confidence_score": 0.04, "investment_horizon": 20, "return_prediction": 0.05}]
`
