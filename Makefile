.PHONY: run-once logs-probe guard-wrap ci-wrap-check

# Boot the game once and run a UI probe in non-interactive mode
run-once:
	printf 'logs trace ui on\nlogs probe wrap --count 24 --width 80\nlogs tail 1\n' | PYTHONPATH=src python -m mutants

# Just the probe (assumes the game is already warmed)
logs-probe:
	printf 'logs trace ui on\nlogs probe wrap --count 24 --width 80\nlogs tail 1\n' | PYTHONPATH=src python -m mutants

# Local guard (read log file and fail on regression)
guard-wrap:
	./scripts/guard_wrap.py

# CI convenience: run probe then guard
ci-wrap-check: logs-probe guard-wrap
