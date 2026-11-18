"""`python manage.py run_pipeline` - runs the whole data workflow.

Usage
-----
    python manage.py run_pipeline                  everything, in order
    python manage.py run_pipeline --reparse        skip reading PDFs again (fast)
    python manage.py run_pipeline --only s05,s06   just these steps
    python manage.py run_pipeline --list           show the steps and stop

The seven steps, in the order they must run:

    s01_catalog        find new PDFs and record them
    s02_extract_text   read their text into the database (slow)
    s03_parse          extract figures, corridors and themes
    s04_events         rebuild the timeline
    s05_export         write the dashboard JSON files
    s06_mcp_layers       rebuild the external map layers from the MCP caches
    s07_xlsx           merge in the Excel layers

Steps 1 and 2 only ever *add* to the database, so re-running is safe. Steps 3
to 7 rebuild what they own from scratch, which is why --reparse (steps 3-7) is
the right choice after changing a parser or a keyword list.

Every step prints "=== name ===" before it starts; the updater page reads those
lines to drive its progress bar, so do not change the format.
"""
import importlib
import time

from django.core.management.base import BaseCommand, CommandError

# (short name, module to import, one-line description shown by --list)
STEPS = [
    ("s01", "data_pipeline.steps.s01_catalog", "catalogue new PDFs"),
    ("s02", "data_pipeline.steps.s02_extract_text", "extract PDF text (slow)"),
    ("s03", "data_pipeline.steps.s03_parse", "parse figures, flows and themes"),
    ("s04", "data_pipeline.steps.s04_events", "rebuild the events timeline"),
    ("s05", "data_pipeline.steps.s05_export", "export the dashboard JSON"),
    ("s06", "data_pipeline.steps.s06_mcp_layers", "rebuild external MCP layers"),
    ("s07", "data_pipeline.steps.s07_xlsx", "merge the Excel layers"),
]
# --reparse skips the two steps that read PDFs off disk.
REPARSE_STEPS = ["s03", "s04", "s05", "s06", "s07"]


class Command(BaseCommand):
    help = "Run the PDF -> database -> dashboard pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reparse", action="store_true",
            help="Re-run parsing and export only (steps 3-7); do not re-read PDFs.",
        )
        parser.add_argument(
            "--only", default="",
            help="Comma-separated step names to run, e.g. --only s06,s07",
        )
        parser.add_argument(
            "--list", action="store_true", dest="list_steps",
            help="Print the available steps and exit.",
        )

    def handle(self, *args, **options):
        if options["list_steps"]:
            for name, module, description in STEPS:
                self.stdout.write(f"{name}  {module.split('.')[-1]:20} {description}")
            return

        # Decide which steps to run.
        if options["only"]:
            wanted = [s.strip() for s in options["only"].split(",") if s.strip()]
            unknown = set(wanted) - {name for name, _, _ in STEPS}
            if unknown:
                raise CommandError(f"unknown step(s): {', '.join(sorted(unknown))}")
        elif options["reparse"]:
            wanted = REPARSE_STEPS
        else:
            wanted = [name for name, _, _ in STEPS]

        started = time.time()
        for name, module_path, _ in STEPS:
            if name not in wanted:
                continue
            step_name = module_path.split(".")[-1]
            # This exact line is what the updater's progress bar looks for.
            self.stdout.write(f"\n=== {step_name} ===")
            self.stdout.flush()

            module = importlib.import_module(module_path)
            module.run()
            self.stdout.flush()

        self.stdout.write(
            self.style.SUCCESS(f"\nPipeline finished in {time.time() - started:.0f}s. "
                               f"Open the dashboard to see the result.")
        )
