# cursor-plan-rebill

Rebills a Cursor usage export on the current plans, so you can compare them with a legacy plan before making the switch. Switching to The X Subscription is permanent, so it is worth measuring first.

## Usage

Export your usage as a CSV from the usage page of your Cursor dashboard. Use at least one full month.

```bash
pip install -r requirements.txt
python cursor_rebill.py usage-events.csv
```

Rates in the script were read on November 3, 2026. Check them against [Cursor's models and pricing page](https://cursor.com/docs/models-and-pricing) before you rely on the result.

## Output

| Line | Meaning |
| --- | --- |
| Pool table | Calculated list value by bucket. `low` and `high` differ only for the unrated bucket |
| Not priced | Models with no rate in the script. Add a rate, or leave them out on purpose |
| Peak 7 days | Your busiest seven days of Cursor-pool usage, with the assumed weekly pool floor |
| Plan lines | Each plan's minimum, and that minimum plus overflow at the floor |

## Method

1. Drop rows marked `Free`, and treat blank token columns as zero.
2. Price each row with `(input × input rate + cache write × cache write rate + cache read × cache read rate + output × output rate) / 1,000,000`.
3. Sort rows by supplier. Grok and Composer draw on the weekly pool, and third-party models are billed at list price.
4. Price Auto and Grok Bot twice, at Composer and Grok 4.7 rates, because neither has a published token rate. The weekly test uses the Composer rates.
5. Add the third-party total to each plan's fee to get its minimum.
6. Estimate the weekly Ultra pool as twice the month's Cursor-pool usage, divided by the weeks in the period. Super gets 30% of that pool and Premium 8%.
7. Walk through the weeks and count everything above the pool as overflow. The reset day is unknown, so the result averages all seven possible reset days.

## Assumptions

- GPT has no rate in the script because OpenAI is leaving Cursor. Add GPT rates to compare.
- Effort levels in model names, such as `-high`, do not change the published rate.
- Every row marked Included means your legacy pool covered at least that month's usage.
- Pools draw down at list rates. Cursor does not confirm this, and it publishes no pool sizes.
- Each new plan has at least twice the Cursor-model usage of the legacy plan it replaces, as Cursor states.
- Overflow is paid at list rates. In practice you can wait for the reset instead.
- Prices exclude VAT, and Teams token fees are not included.

The result is an estimate from one export. Your dashboard's Spending tab shows your real legacy limits.
