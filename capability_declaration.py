#!/usr/bin/env python3
"""AURELIX-CAPABILITY declaration for the `migrate` CLI (URL redirect migration toolkit).

WHY THIS IS A SEPARATE FILE, AND NOT `src/migrate/cli.py`
--------------------------------------------------------
`--describe` must run with no arguments, do no work, and reach the compiler
under the ambient interpreter.  `cli.py` imports `typer` and `rich` at module
scope and this package declares `requires-python = ">=3.11"`, while local
`python3` is 3.9.6 — so `python3 src/migrate/cli.py --describe` cannot work
outside `.venv/bin`.

And NO IMPORT MAY REACH web-builder: `web-builder` and `aurelix-uiux-audit`
both ship a top-level package named `lib`, the first import wins for the
process, and that collision has already killed an instrument.  So this file
imports `json` and `sys` and nothing else, and prints the declaration literally.
`capability_register.py` re-validates it through `lib.capability.validate`
whatever produced the JSON.

ONE DECLARATION, NINE COMMANDS
------------------------------
`init discover fetch map validate upload verify rollback pipeline` are one
instrument: one console script, one package, one venv, and every command after
`init` is driven by the same `config.yaml`.  `pipeline` is literally the other
eight run in order.  Nine register rows would be nine rows that cannot be run
independently.

    python3 capability_declaration.py --describe
"""
from __future__ import annotations

import json
import sys

# AURELIX-CAPABILITY
CAPABILITY = {
    "id": "aurelix.migration.url-redirects",
    "name": "URL redirect migration toolkit — maps legacy CMS URLs onto Shopify and uploads them",
    "kind": "migration",
    "invocation": (
        "cd shopify-url-redirect-migration-toolkit && "
        ".venv/bin/migrate init --name <project> [--output <dir>]   then, inside it, "
        ".venv/bin/migrate <discover|fetch|map|validate|upload|verify|rollback|pipeline> "
        "[--config config.yaml] [--dry-run] [-v]"
    ),
    "preconditions": [
        "Python >= 3.11 in a venv: `python3.12 -m venv .venv && .venv/bin/pip install -e .` — "
        "local python3 is 3.9.6 and python3.11 does not exist here; the console script lives "
        "only in .venv/bin",
        "The submodule must be initialised: `git submodule update --init --recursive`",
        "`init` takes --name/-n <str> and --output/-o <dir> and NOTHING ELSE. The "
        "`--source wordpress --target shopify` shown in older Aurelix docs does not exist: "
        "source and target are config.yaml FIELDS (verified 2026-08-18 against `init --help`)",
        "Every command except `init` reads config.yaml (--config/-c, default ./config.yaml)",
        "upload / verify / rollback / pipeline need SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN "
        "in the environment, interpolated into config.yaml by the ${VAR} expander "
        "(src/migrate/config.py:168-172). MEASURED 2026-08-18: neither is set on this machine",
        "discover needs network access to the Wayback CDX API and/or the source sitemap",
    ],
    "inputs": [
        "config.yaml — source domains, target store, mapping rules, output directory",
        "Wayback Machine CDX responses and the source sitemap.xml (discover)",
        "the source platform's API and the Shopify Admin REST API (fetch)",
        "the redirect CSV under <output>/04_redirect_mapping (validate, upload, verify)",
        "the upload manifest written by a previous upload (rollback)",
    ],
    "outputs": [
        "a scaffolded project tree from `init`: config.yaml plus 00_source_data, "
        "01_normalized_data, 03_mapping_rules, 04_redirect_mapping, 06_output, tests "
        "(measured — that is exactly what appeared)",
        "discovered and normalised URL sets under 00_source_data / 01_normalized_data",
        "the redirect CSV (from_path,to_path[,status]) under 04_redirect_mapping — the same "
        "shape web-builder/scripts/verify_gate_e.py reads via --redirect-map",
        "validation reports under 06_output",
        "redirects created in a live Shopify store, and an upload manifest for rollback",
    ],
    "outcome": (
        "A reviewed, validated set of legacy-URL -> Shopify-URL redirects, and — only if you "
        "run upload — those redirects created in a live store, with a manifest that lets you "
        "undo them. Nothing in the Aurelix chain invokes this toolkit: a repo-wide grep of "
        "run_pipeline.py and web-builder/scripts finds no call site (measured 2026-08-18). "
        "Gate E consumes a redirect map of this shape but never produces one."
    ),
    "exit_contract": {
        "0": "the command completed: for upload/verify/rollback the underlying operation "
             "returned success; for pipeline, steps_failed == 0",
        "1": "raised via typer.Exit(1): upload/verify/rollback returned failure, pipeline "
             "finished with at least one failed step, or `discover` found no configured "
             "discovery source",
        "2": "usage error from Typer/Click — unknown command, or `init` without --name",
    },
    "measures": [
        "historical URLs recoverable from Wayback and the source sitemap",
        "source -> target URL matches and the confidence of each match",
        "CSV conformance to Shopify's redirect import format",
        "whether each mapped target actually exists in the target store",
        "redirect chains (a redirect whose target is itself redirected)",
        "live HTTP behaviour of a sample of uploaded redirects: 301 status and Location header",
    ],
    "cannot_see": [
        "IT HAS NEVER BEEN MEASURED AGAINST A STORE FROM THIS REPO. upload and rollback MUTATE "
        "A LIVE SHOPIFY STORE and were deliberately not run; SHOPIFY_STORE_URL and "
        "SHOPIFY_ACCESS_TOKEN are unset here (measured: 0 matches in the environment), so the "
        "entire upload/verify/rollback half is NOT_RUN, not passing",
        "Its 105 passing tests touch neither the network nor a store, so a green suite is not "
        "evidence that upload works — the same shape of false comfort that made "
        "shopify-bulk-product-importer's 53 green tests hide a CLI that cannot import",
        "It cannot see a legacy URL that appears in neither Wayback nor the sitemap; anything "
        "undiscovered is silently absent from the map rather than reported as unmapped",
        "It cannot see whether a mapped target renders the RIGHT page — target-existence "
        "validation checks that a URL resolves, not that its content corresponds to the legacy "
        "page's content",
        "`pipeline` cannot see which URLs a partially-failed run left unmigrated: each step is "
        "wrapped in `except Exception`, counted into steps_failed and the pipeline continues; "
        "the exit is 1 with a step count, and discovery failures are downgraded to warnings and "
        "counted as steps RUN (cli.py, Step 1)",
        "It cannot see SEO consequences: nothing measures traffic, rankings or crawl budget "
        "before or after the migration",
    ],
    "reachable_from": [],
    "cost": (
        "`init` is instant and offline. discover/fetch are network-bound and Wayback CDX can "
        "take minutes on a large domain. upload writes to a live Shopify store, is batch-paced, "
        "and is the only irreversible step (rollback needs its manifest). Own suite: 105 tests, "
        "5.4s (`.venv/bin/python -m pytest -q`, measured 2026-08-18)."
    ),
}


def main() -> int:
    if "--describe" in sys.argv[1:]:
        print(json.dumps(CAPABILITY, indent=2))
        return 0
    print(
        "This file declares the capability of the `migrate` console script.\n"
        "Run `python3 capability_declaration.py --describe` for the declaration, or\n"
        "`.venv/bin/migrate --help` for the instrument itself.",
        file=sys.stderr,
    )
    return 64


if __name__ == "__main__":
    sys.exit(main())
