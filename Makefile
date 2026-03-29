.PHONY: arch-check arch-fix

arch-check:
	python tools/check_architecture.py

arch-fix:
	@echo ""
	@echo "Architecture violations are not auto-fixable."
	@echo "For each violation, apply one of these fixes:"
	@echo ""
	@echo "  layer       Move the import behind an interface, or add an exception"
	@echo "              to PRESENTATION_APP_SERVICE_EXCEPTIONS / INFRA_APP_SERVICE_EXCEPTIONS"
	@echo "              in tools/check_architecture.py with a comment explaining why."
	@echo ""
	@echo "  eventbus    Route the publish through a Qt signal (see OstSignaler pattern"
	@echo "              in service_builder.py), or move the publish to a main-thread callback."
	@echo ""
	@echo "  lifecycle   A class should not implement both cleanup() and IShutdownAware."
	@echo "              Use cleanup() if a parent owns teardown; use IShutdownAware if the"
	@echo "              container should discover it via get_by_interface()."
	@echo ""
	@echo "  interface   Protocol classes must start with I (e.g. IFoo). ABC is only allowed"
	@echo "              for classes discovered at runtime: IShutdownAware, IStartable,"
	@echo "              IAnnotationViewManager. To add a new ABC, update ALLOWED_ABCS in"
	@echo "              tools/check_architecture.py."
	@echo ""
	@echo "  logging     Move logging.getLogger() to module level or __init__. Do not create"
	@echo "              loggers inside function/method bodies."
	@echo ""
	@echo "  cpp         Each .pyd has one canonical location (see CLAUDE.md table)."
	@echo "              Remove duplicates. Import C++ modules only from their layer."
	@echo ""
	@echo "Run 'make arch-check' to see current violations."
	@echo ""
