"""Local, offline baseline operator. Never routes to an active F5 account."""
import argparse
import json
from pathlib import Path
import sys

from .store import Journal

DEFAULT_JOURNAL=Path(__file__).resolve().parents[1]/'data/nautilus-baseline/journal.sqlite3'
DEFAULT_SHADOW_STORE=Path(__file__).resolve().parents[1]/'data/nautilus-baseline/shadow_decisions.sqlite3'


def main():
    parser=argparse.ArgumentParser(description='Nautilus离线模拟基线：运行、恢复与核验')
    parser.add_argument('--journal',type=Path)
    parser.add_argument('--shadow-store',type=Path)
    commands=parser.add_subparsers(dest='action',required=True)
    run=commands.add_parser('run')
    run.add_argument('--input',type=Path,required=True)
    run.add_argument('--id',required=True)
    commands.add_parser('recover')
    commands.add_parser('status')
    for action in ('account-append','account-status','account-recover'):
        command=commands.add_parser(action)
        command.add_argument('--account',required=True)
        if action=='account-append':
            command.add_argument('--input',type=Path,required=True)
            command.add_argument('--id',required=True)
            command.add_argument('--expected-revision',type=int,required=True)
    probe=commands.add_parser('data-probe')
    probe.add_argument('--codes',required=True,help='逗号分隔的六位股票代码，最多20只')
    probe.add_argument('--report',type=Path,help='新建JSON报告；不覆盖已有文件')
    baseline_export=commands.add_parser('baseline-export')
    baseline_export.add_argument('--input',type=Path,required=True)
    baseline_export.add_argument('--output',type=Path,required=True)
    shadow_record=commands.add_parser('shadow-record')
    shadow_record.add_argument('--input',type=Path,required=True)
    shadow_report=commands.add_parser('shadow-report')
    shadow_report.add_argument('--limit',type=int,default=100)
    shadow_run=commands.add_parser('shadow-run')
    shadow_run.add_argument('--context',type=Path,required=True)
    shadow_ai_run=commands.add_parser('shadow-ai-run')
    shadow_ai_run.add_argument('--context',type=Path,required=True)
    shadow_ai_run.add_argument('--raw-output',type=Path,required=True)
    shadow_context=commands.add_parser('shadow-context-build')
    shadow_context.add_argument('--baseline-result',type=Path,required=True)
    shadow_context.add_argument('--market-summary',type=Path)
    shadow_context.add_argument('--risk-summary',type=Path)
    shadow_context.add_argument('--factor-summary',type=Path)
    shadow_context.add_argument('--strategy-summary',type=Path)
    shadow_context.add_argument('--history-summary',type=Path)
    shadow_context.add_argument('--output',type=Path)
    shadow_cycle=commands.add_parser('shadow-cycle')
    shadow_cycle.add_argument('--runtime-summary',type=Path)
    shadow_cycle.add_argument('--baseline-result',type=Path)
    shadow_cycle.add_argument('--market-summary',type=Path)
    shadow_cycle.add_argument('--risk-summary',type=Path)
    shadow_cycle.add_argument('--factor-summary',type=Path)
    shadow_cycle.add_argument('--strategy-summary',type=Path)
    shadow_cycle.add_argument('--history-summary',type=Path)
    shadow_cycle.add_argument('--raw-output',type=Path,required=True)
    shadow_cycle.add_argument('--context-output',type=Path)
    shadow_cycle.add_argument('--report-output',type=Path)
    shadow_runtime=commands.add_parser('shadow-runtime-summary')
    shadow_runtime.add_argument('--baseline-result',type=Path,required=True)
    shadow_runtime.add_argument('--market-summary',type=Path)
    shadow_runtime.add_argument('--risk-summary',type=Path)
    shadow_runtime.add_argument('--factor-summary',type=Path)
    shadow_runtime.add_argument('--strategy-summary',type=Path)
    shadow_runtime.add_argument('--history-summary',type=Path)
    shadow_runtime.add_argument('--output',type=Path,required=True)
    shadow_ai_output=commands.add_parser('shadow-ai-output')
    shadow_ai_output.add_argument('--runtime-summary',type=Path,required=True)
    shadow_ai_output.add_argument('--raw-output',type=Path,required=True)
    shadow_ai_output.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        mode='offline_replay'
        code=0
        if args.action=='data-probe':
            from .intake import capture_snapshot
            if args.report and (args.report.suffix.lower()!='.json' or args.report.exists()):
                raise ValueError('new_json_report_required')
            data=capture_snapshot([value.strip() for value in args.codes.split(',')])
            mode='data_observation'
            code=0 if data['execution_ready'] else 2
            if args.report:
                args.report.parent.mkdir(parents=True,exist_ok=True)
                with args.report.open('x',encoding='utf-8') as output:
                    json.dump(data,output,ensure_ascii=False,indent=2)
        elif args.action=='baseline-export':
            from .baseline_export import publish_baseline_result
            data=publish_baseline_result(source_path=args.input,output_path=args.output)
            mode='shadow_decision'
        elif args.action=='shadow-context-build':
            from .shadow_context_builder import build_runtime_shadow_context, load_json
            data=build_runtime_shadow_context(
                baseline_result=load_json(args.baseline_result),
                market_summary=load_json(args.market_summary) if args.market_summary else None,
                risk_summary=load_json(args.risk_summary) if args.risk_summary else None,
                factor_summary=load_json(args.factor_summary) if args.factor_summary else None,
                strategy_summary=load_json(args.strategy_summary) if args.strategy_summary else None,
                history_summary=load_json(args.history_summary) if args.history_summary else None,
            )
            if args.output:
                args.output.parent.mkdir(parents=True,exist_ok=True)
                with args.output.open('x',encoding='utf-8') as output:
                    json.dump(data,output,ensure_ascii=False,indent=2)
                data={'path':str(args.output),'context':data}
            mode='shadow_decision'
        elif args.action=='shadow-cycle':
            from .shadow_context_builder import load_json
            from .shadow_cycle import run_shadow_cycle
            from .shadow_decision_store import ShadowDecisionJournal
            if args.runtime_summary is None and args.baseline_result is None:
                raise ValueError('runtime_summary_or_baseline_required')
            with ShadowDecisionJournal(args.shadow_store or DEFAULT_SHADOW_STORE) as journal:
                data=run_shadow_cycle(
                    runtime_summary=load_json(args.runtime_summary) if args.runtime_summary else None,
                    baseline_result=load_json(args.baseline_result) if args.baseline_result else None,
                    market_summary=load_json(args.market_summary) if args.market_summary else None,
                    risk_summary=load_json(args.risk_summary) if args.risk_summary else None,
                    factor_summary=load_json(args.factor_summary) if args.factor_summary else None,
                    strategy_summary=load_json(args.strategy_summary) if args.strategy_summary else None,
                    history_summary=load_json(args.history_summary) if args.history_summary else None,
                    raw_output=args.raw_output.read_text(encoding='utf-8'),
                    journal=journal,
                    context_output=args.context_output,
                    report_output=args.report_output,
                )
            mode='shadow_decision'
        elif args.action=='shadow-runtime-summary':
            from .shadow_runtime_summary import build_shadow_runtime_summary, load_json
            data=build_shadow_runtime_summary(
                baseline_result=load_json(args.baseline_result),
                market_summary=load_json(args.market_summary) if args.market_summary else None,
                risk_summary=load_json(args.risk_summary) if args.risk_summary else None,
                factor_summary=load_json(args.factor_summary) if args.factor_summary else None,
                strategy_summary=load_json(args.strategy_summary) if args.strategy_summary else None,
                history_summary=load_json(args.history_summary) if args.history_summary else None,
            )
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x',encoding='utf-8') as output:
                json.dump(data,output,ensure_ascii=False,indent=2)
            data={'path':str(args.output),'runtime_summary':data}
            mode='shadow_decision'
        elif args.action=='shadow-ai-output':
            from .shadow_ai_provider import publish_shadow_ai_output
            data=publish_shadow_ai_output(runtime_summary_path=args.runtime_summary,
                                          raw_output_path=args.raw_output,
                                          output_path=args.output)
            mode='shadow_decision'
        elif args.action.startswith('shadow-'):
            from .shadow_decision_store import ShadowDecisionJournal
            with ShadowDecisionJournal(args.shadow_store or DEFAULT_SHADOW_STORE) as journal:
                if args.action=='shadow-record':
                    data=journal.record(json.loads(args.input.read_text(encoding='utf-8')))
                elif args.action=='shadow-run':
                    from .shadow_runner import run_shadow_decision
                    data=run_shadow_decision(json.loads(args.context.read_text(encoding='utf-8')),journal=journal)
                elif args.action=='shadow-ai-run':
                    from .shadow_ai_adapter import run_shadow_ai
                    data=run_shadow_ai(json.loads(args.context.read_text(encoding='utf-8')),
                                       raw_output=args.raw_output.read_text(encoding='utf-8'),journal=journal)
                else:
                    data=journal.report(args.limit)
            mode='shadow_decision'
        elif args.action.startswith('account-'):
            from .continuous import ContinuousAccount
            if args.journal is None:
                raise ValueError('explicit_account_journal_required')
            with ContinuousAccount(args.journal,args.account) as account:
                if args.action=='account-append':
                    data=account.append(args.id,json.loads(args.input.read_text(encoding='utf-8')),
                                        args.expected_revision)
                elif args.action=='account-recover':data=account.recover()
                else:data=account.status()
            mode='continuous_full_replay'
        else:
            with Journal(args.journal or DEFAULT_JOURNAL) as journal:
                if args.action=='run':
                    data=journal.execute(args.id,json.loads(args.input.read_text(encoding='utf-8')))
                elif args.action=='recover':data=journal.recover()
                else:data=journal.status()
        print(json.dumps({'success':True,'mode':mode,'data':data},ensure_ascii=True))
        return code
    except Exception as exc:
        print(json.dumps({'success':False,'reason':str(exc),'live_execution_authority':False},ensure_ascii=True))
        return 1


if __name__=='__main__':
    sys.exit(main())
