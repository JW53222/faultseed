# Thin wrapper -- there is nothing to build here, only checks to run.
# `run_tests.sh` is the single source of truth for what "passing" means;
# these targets just give it short, memorable names.

.PHONY: test check examples clean

# Run everything: every pytest suite in the tree plus the examples/
# planted-failure checks. Same command CI runs.
test:
	./run_tests.sh

# Alias, for the muscle-memory of typing `make check`.
check: test

# Run only the examples/ planted-failure checks (skips the pytest suites).
# Useful when you're iterating on an example and don't want to wait for the
# full hook test suite each time.
examples:
	./examples/run_all.sh

# Remove bytecode caches and pytest's own cache dir. Does not touch
# anything examples/ or run_tests.sh created -- those clean up after
# themselves (see examples/lib/common.sh's `trap ... EXIT`).
clean:
	find . -type d -name '__pycache__' -not -path './.git/*' -exec rm -rf {} +
	rm -rf .pytest_cache
