'use client'

import type { ComplianceData } from '@/lib/types'

interface Props {
  compliance: ComplianceData | undefined
  filtered: boolean
  onToggleFilter: () => void
}

export default function ComplianceBar({ compliance, filtered, onToggleFilter }: Props) {
  if (compliance === undefined) {
    return <div className="h-5 w-40 rounded bg-raised animate-pulse" />
  }

  if (compliance.compliant) {
    return (
      <div className="flex items-center gap-1.5 font-mono text-xs text-green-500/80">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
        COMPLIANT
      </div>
    )
  }

  const count = compliance.violations.length

  return (
    <div className="flex flex-col min-w-0 max-w-xl">
      <button
        onClick={onToggleFilter}
        title={
          filtered
            ? 'Click to show full tree'
            : `Click to filter tree to ${count} violation${count !== 1 ? 's' : ''}`
        }
        className={[
          'flex items-center gap-1.5 px-2.5 py-0.5 rounded text-xs font-mono w-fit',
          'border transition-all duration-150 select-none',
          filtered
            ? 'bg-violation/10 border-violation/60 text-violation'
            : 'border-violation/40 text-violation/80 hover:border-violation/70 hover:text-violation',
        ].join(' ')}
      >
        <span
          className={`w-1.5 h-1.5 rounded-full bg-violation flex-shrink-0 ${
            !filtered ? 'animate-pulse' : ''
          }`}
        />
        <span>
          {count} VIOLATION{count !== 1 ? 'S' : ''}
        </span>
        {filtered && <span className="ml-1 text-lo">— CLEAR</span>}
      </button>
      <ul className="mt-0.5 space-y-0 font-mono text-[10px] text-violation/80 leading-tight">
        {compliance.violations.map((v) => (
          <li key={`${v.level}:${v.path}`} title={v.reason}>
            {v.level} · {v.path} ({v.child_count})
          </li>
        ))}
      </ul>
    </div>
  )
}
