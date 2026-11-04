# FRC AI Scouting Pipeline

A multi-stage competitive intelligence pipeline for FIRST Robotics Competition (FRC) events. Built for Team 3158 (PrepaTec TECBOT) during the 2026 season.

## What it does

Pulls live match and team data from The Blue Alliance API, runs a Monte Carlo tournament simulator to predict final rankings, aggregates statistical and human scouting data per team, and runs dual-model AI analysis (Gemini + GPT-4o) to generate structured scouting reports for alliance selection and match strategy.

## Pipeline stages

**base.py** — Scrapes OPR, DPR, CCWM, match predictions, ranking predictions, and stat distributions from the TBA API for a given event. Outputs clean CSVs to /data.

**montecarlo.py** — Simulates the full tournament 100 times using OPR-based match simulation with calibrated RP rates pulled from real match data. Outputs predicted rankings and average RP per team.

**buldteamdatafunc.py** — Aggregates all data sources (TBA stats, Monte Carlo results, human scouting, metadata) into a single structured dict per team.

**analysts.py** — Runs each team through Gemini and GPT-4o in parallel using a structured analyst prompt. Produces prose scouting reports + structured JSON output covering tier rating, cycle profile, alliance role, RP contributions, strengths, weaknesses, and match strategy.

## Sample Output

![Sample scouting report for Team 358](sample_output.png)

Each team receives independent analysis from Gemini and GPT-4o covering performance summary, autonomous, teleop, cycle profile, strengths, weaknesses, and match strategy.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file based on `.env.example`:

TBAKEY=your_tba_api_key
GEMINI_KEY=your_gemini_key
OPENAI_KEY=your_openai_key

## Usage

```bash
python -m pipeline.base          # Pull and process TBA data
python -m pipeline.montecarlo    # Run tournament simulation
python -m pipeline.analysts      # Generate AI scouting reports
```

## Stack

Python, pandas, numpy, The Blue Alliance API, Google Gemini, OpenAI GPT-4o