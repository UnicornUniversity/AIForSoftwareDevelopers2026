# Lottery Numbers

## Problem Statement

I have a CSV file named `eurojackpot.csv` that contains historical lottery draw data. The file has the following structure:

- Date of a draw
- Year (four digits)
- Number #1 from Set #1
- Number #2 from Set #1
- Number #3 from Set #1
- Number #4 from Set #1
- Number #5 from Set #1
- Number #1 from Set #2
- Number #2 from Set #2

## Your Tasks

1. **Data Analysis**: Analyze the historical lottery draw data to identify any patterns or trends in the numbers drawn. This could include frequency analysis of each number, identifying hot and cold numbers, and any correlations between the numbers drawn.
2. **Predictive Modeling**: Based on your analysis, develop a predictive model that can suggest potential winning numbers for future draws. This model should take into account the historical data and any identified patterns.
3. **Visualization**: See details below.

Save your analysis in a new MD file and in a local Jupiter Notebook.

## Visualization Details

### Heatmap

Create a heatmap.html file that visually represents the frequency of each number drawn in the lottery. The file should have two heatmaps: one for Set #1 and another one for Set #2. Use D3.js library for this.

### Bar Chart

Create a barchart.html file that shows the frequency of draw numbers separately for Set #1 and Set #2. Use D3.js library for this.
Below the two charts, place a plaque with information:

- 5 the most frequently drawn numbers from Set #1
- 2 the most frequently drawn numbers from Set #2

