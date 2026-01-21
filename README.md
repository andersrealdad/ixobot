# The Garage

Where ideas get built before they're ready for the world.

> "The biggest companies started in garages. This is mine."

## Structure
```
garage/
├── notebooks/     # Jupyter experiments
├── experiments/   # One-off scripts
└── .venv/         # Python environment
```

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install mlflow jupyterlab pandas numpy matplotlib scikit-learn
jupyter lab
```

## Rules
- Experiments stay here until proven useful
- Promote mature code to appropriate repo (ASTRID, GriffinHub, etc.)
- Clean up failed experiments regularly
- Break things. Learn. Build again.

## MLflow Tracking
```python
import mlflow
mlflow.set_experiment("garage")

with mlflow.start_run():
    mlflow.log_param("idea", "crazy")
    mlflow.log_metric("potential", 100)
```
