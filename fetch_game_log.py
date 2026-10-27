name: Update NBA Game Log
on:
  schedule:
    - cron: "15 * * * *"
  workflow_dispatch:
permissions:
  contents: write
jobs:
  update-game-log:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Append 2026-27 box scores
        run: python fetch_game_log.py
      - name: Build the DVP sheet
        run: python build_dvp.py
      - name: Commit
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add nba_game_log.csv nba_dvp.csv
          git diff --staged --quiet || git commit -m "Update NBA game log and DVP $(date -u +%F)"
          git push
