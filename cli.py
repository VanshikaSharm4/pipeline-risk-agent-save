#!/usr/bin/env python3
"""Pipeline risk agent CLI."""

from __future__ import annotations

import argparse
import json
import sys

import config


def cmd_verify(args: argparse.Namespace) -> int:
    from connectors import splunk_csv

    if args.target in ("splunk", "all"):
        df = splunk_csv.load_pipelines()
        dev, prod = splunk_csv.split_dev_prod(df)
        print(f"OK splunk: program={config.PROGRAM_ID} dev={len(dev)} prod={len(prod)} total={len(df)}")
        if args.exec:
            row = splunk_csv.get_execution_row(df, args.exec)
            print(f"  execution {args.exec}: {'found' if row is not None else 'NOT FOUND'}")

    if args.target in ("azure", "all") and args.exec:
        from connectors import azure_logs, splunk_csv

        df = splunk_csv.load_pipelines()
        shares = splunk_csv.load_share_names()
        row = splunk_csv.get_execution_row(df, args.exec)
        if not row:
            print(f"FAIL: execution {args.exec} not in CSV")
            return 1
        share = shares.get(str(args.exec), "")
        deploy = str(row.get("Deploy Start Time", ""))
        print(f"Share: {share}")
        for step in ("build", "securityTest", "deploy", "loadTest"):
            log = azure_logs.get_log(str(args.exec), share, step, deploy_start=deploy)
            status = "OK" if log and not log.startswith("ERROR:") else "MISS"
            print(f"  {step}: {status} ({len(log)} chars)")
            if log.startswith("ERROR:"):
                print(f"    {log[:120]}")
        discovered = azure_logs.discover_log_paths(share, str(args.exec)) if share else {}
        if discovered:
            print(f"  discovered paths: {discovered}")

    if args.target in ("commit", "all") and args.exec:
        from connectors import commit_resolver, splunk_csv

        df = splunk_csv.load_pipelines()
        shares = splunk_csv.load_share_names()
        row = splunk_csv.get_execution_row(df, args.exec)
        share = shares.get(str(args.exec), "")
        sha = commit_resolver.resolve_for_execution(
            str(args.exec), share, str(row.get("Deploy Start Time", "")) if row else None
        )
        print(f"OK commit: {sha or 'NOT RESOLVED (use --commit override)'}")

    if args.target in ("git", "all"):
        from connectors import git_connector, git_local

        git_connector.clone_or_update()
        sha = args.commit
        if not sha:
            from connectors import splunk_csv
            df = splunk_csv.load_pipelines()
            rows = df.head(3).to_dict("records")
            for r in rows:
                r["executionId"] = str(r.get("executionId", ""))
            corr = git_connector.correlate_executions_to_commits(rows)
            print(f"OK git: repo synced, sample correlations={len(corr)}")
        else:
            info = git_local.analyze_commit(sha)
            print(f"OK git: modules={info.get('modules')} flags={info.get('flags')}")

    return 0


def cmd_index(args: argparse.Namespace) -> int:
    if args.no_vector:
        import os
        os.environ["ENABLE_VECTOR_TRACK"] = "false"
    from analysis.dual_track_build import build_dual_track

    result = build_dual_track()
    print(json.dumps(result, indent=2))
    return 0


def cmd_scan_archive(args: argparse.Namespace) -> int:
    from connectors.azure_archive_scan import scan_archive

    print(json.dumps(scan_archive(), indent=2))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Full dual-track build: scan archive → Track A → Track B."""
    print("=== Step 1: Scan Azure archive ===")
    from connectors.azure_archive_scan import scan_archive
    scan = scan_archive()
    print(f"Archive: {scan.get('archive_dir')}")
    print(f"Coverage: {scan.get('coverage_pct')}% ({scan.get('executions_with_logs')} executions)")

    if scan.get("coverage_pct", 0) < 10:
        print("WARNING: Low archive coverage. Set LOG_ARCHIVE_DIR to your 30-day Azure files.")
        print("Expected layout: data/log_archive/{executionId}/build.log")

    print("\n=== Step 2: Build Track A + Track B ===")
    from analysis.dual_track_build import build_dual_track
    result = build_dual_track()
    print(json.dumps(result, indent=2))
    print("\nDone. Run: python3 cli.py score --dev-exec <id>")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    from analysis.transfer_stats import load_stats
    from analysis.pair_builder import load_pairs

    pairs = load_pairs()
    stats = load_stats()
    print(f"Program {config.PROGRAM_ID} | window {config.HISTORY_WINDOW_DAYS}d")
    print(f"Pairs: {len(pairs)} | dev_pass→prod_fail: {stats.get('n_dev_pass_prod_fail', 0)}")
    print(f"Baseline P(prod_fail|dev_pass): {stats.get('baseline_p_prod_fail_given_dev_pass', 0):.2%}")
    print("By module:", json.dumps(stats.get("by_module", {}), indent=2))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from agent.orchestrator import score_dev_execution

    live = not getattr(args, "no_live", False)
    if live:
        print("Fetching latest Splunk data (dev + prod)…")
    report = score_dev_execution(args.dev_exec, commit_override=args.commit, live=live)
    print(report.markdown)
    print(f"\nWritten: reports/risk_{args.dev_exec}.json")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from analysis.backtest import run_backtest

    s = run_backtest()
    print(f"Backtest n={s['n_scored']} precision@High={s['precision_at_high']:.2%} false_comfort={s['false_comfort_count']}")
    return 0


def cmd_fetch_splunk(args: argparse.Namespace) -> int:
    from connectors.splunk_api import fetch_all_pipelines, save_pipelines_csv

    print(f"Fetching Splunk: program={config.PROGRAM_ID} dev={config.PIPELINE_ID_DEV} prod={config.PIPELINE_ID_PROD}...")
    df = fetch_all_pipelines()
    path = save_pipelines_csv(df)
    print(f"Saved {len(df)} executions → {path}")
    return 0


def cmd_archive_azure(args: argparse.Namespace) -> int:
    from analysis.azure_archiver import archive_all_from_csv, archive_dir

    print(f"Archiving to {archive_dir()}...")
    m = archive_all_from_csv(limit=args.limit, force=args.force, pipeline=args.pipeline)
    saved = sum(len(r.get("saved", [])) for r in m.get("results", []))
    print(f"Done: {m['count']} executions, {saved} new log files")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    from connectors import splunk_csv

    df = splunk_csv.load_pipelines()
    dev, prod = splunk_csv.split_dev_prod(df)
    target = dev if args.pipeline == "dev" else prod
    cols = ["executionId", "Status", "pipelineName", "Deploy Start Time"]
    print(target[cols].to_string(index=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Pipeline risk agent (Program 19905)")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="Verify connectors")
    v.add_argument("target", choices=["splunk", "azure", "commit", "git", "all"], default="all", nargs="?")
    v.add_argument("--exec", help="Execution ID for azure/commit checks")
    v.add_argument("--commit", help="SHA for git verify")
    v.set_defaults(func=cmd_verify)

    ix = sub.add_parser("index", help="Rebuild historical index")
    ix.add_argument("--rebuild", action="store_true")
    ix.add_argument("--no-vector", action="store_true", help="Skip vector index build")
    ix.set_defaults(func=cmd_index)

    sub.add_parser("history", help="Print transfer stats summary").set_defaults(func=cmd_history)

    sc = sub.add_parser("score", help="Score dev execution for prod risk (fetches Splunk live by default)")
    sc.add_argument("--dev-exec", required=True, dest="dev_exec")
    sc.add_argument("--commit", help="Override commit SHA")
    sc.add_argument("--no-live", action="store_true", dest="no_live",
                    help="Skip live Splunk fetch; use cached CSV only")
    sc.set_defaults(func=cmd_score)

    sub.add_parser("backtest", help="Backtest structured track").set_defaults(func=cmd_backtest)

    ls = sub.add_parser("list", help="List executions in window")
    ls.add_argument("--pipeline", choices=["dev", "prod"], default="dev")
    ls.set_defaults(func=cmd_list)

    fs = sub.add_parser("fetch-splunk", help="Fetch dev+prod pipelines from Splunk API")
    fs.set_defaults(func=cmd_fetch_splunk)

    sub.add_parser("scan-archive", help="Scan LOG_ARCHIVE_DIR vs Splunk CSV").set_defaults(func=cmd_scan_archive)

    bd = sub.add_parser("build", help="Full dual-track build (archive + Track A + Track B)")
    bd.set_defaults(func=cmd_build)

    aa = sub.add_parser("archive-azure", help="Download Azure logs to local archive")
    aa.add_argument("--pipeline", choices=["all", "dev", "prod"], default="all")
    aa.add_argument("--limit", type=int, default=0)
    aa.add_argument("--force", action="store_true")
    aa.set_defaults(func=cmd_archive_azure)

    args = p.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
