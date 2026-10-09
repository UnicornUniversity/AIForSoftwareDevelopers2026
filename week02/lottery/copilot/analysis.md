# Lottery analysis: Eurojackpot

## Dataset
- **Draws analyzed:** 821
- **Main numbers:** 5 numbers from 1-50
- **Star numbers:** 2 numbers from 1-12

## What I looked at
- Frequency counts for every number in both sets
- Hot and cold numbers
- Pair co-occurrence among the 5 main numbers
- Odd/even balance and total-sum range
- A simple heuristic prediction model based on long-term frequency plus recent momentum

## Key findings

### Main numbers
| Rank | Number | Count |
|---|---:|---:|
| 1 | 20 | 102 |
| 2 | 35 | 95 |
| 3 | 11 | 94 |
| 4 | 16 | 94 |
| 5 | 34 | 94 |

The coldest main numbers were **25**, **48**, **10**, **28**, and **5**.

### Star numbers
| Rank | Number | Count |
|---|---:|---:|
| 1 | 5 | 164 |
| 2 | 3 | 161 |
| 3 | 9 | 159 |
| 4 | 6 | 151 |
| 5 | 8 | 149 |

The coldest star numbers were **11**, **12**, and **2**.

### Structure and trends
- The draw mix is usually balanced: **2 odd / 3 even** and **3 odd / 2 even** main-number splits were the most common.
- Main-number sums ranged from **43** to **221**, with an average of **138.86**.
- Several pairs repeated more often than chance would suggest in a small sample, with the strongest observed pair being **34 + 49**.

## Predictive model
I used a simple heuristic score for each number:

> **score = long-term frequency + 2 x recent-100-draw frequency**

This is not a true predictor - lottery draws remain random - but it gives a reproducible way to weight numbers that have been consistently active recently.

### Suggested ticket from the heuristic
- **Main numbers:** 35, 21, 18, 37, 8
- **Stars:** 6, 5

## Notes
- All numbers in both sets appeared at least once in the dataset.
- The D3 visualizations are stored in this same folder as `heatmap.html` and `barchart.html`.
