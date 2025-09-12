.ONESHELL:
.PHONY: run-once logs-probe guard-wrap ci-wrap-check

# Boot the game once and run a UI probe in non-interactive mode
run-once:
	python -m mutants <<'EOF'
	logs trace ui on
	logs probe wrap --count 24 --width 80
	logs tail 1
	EOF

# Just the probe (assumes the game is already warmed)
logs-probe:
	python -m mutants <<'EOF'
	logs trace ui on
	logs probe wrap --count 24 --width 80
	logs tail 1
	EOF

# Local guard (read log file and fail on regression)
guard-wrap:
	./scripts/guard_wrap.py

# CI convenience: run probe then guard
ci-wrap-check: logs-probe guard-wrap
