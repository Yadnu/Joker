'use client'

import Link from 'next/link'
import { describeTurn, type TurnGroup, type TurnFields } from '@/lib/turns'

export default function TurnHeader<T extends TurnFields>({
  group,
  open,
  onToggle,
}: {
  group: TurnGroup<T>
  open: boolean
  onToggle: () => void
}) {
  const d = describeTurn(group)
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full text-left py-2 group"
      aria-expanded={open}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[9px] text-lo/50">{open ? '▾' : '▸'}</span>
        <span className="font-mono text-[10px] font-bold uppercase tracking-wider text-hi">
          {d.kicker}
        </span>
      </div>
      {d.quoted ? (
        <p className="mt-1 pl-5 font-mono text-[11px] text-mid leading-relaxed">
          “{d.subtitle}”
        </p>
      ) : d.replacedJokeId ? (
        <p className="mt-1 pl-5 font-mono text-[11px] text-mid leading-relaxed">
          Replacing{' '}
          <Link
            href={`/viewer?joke=${encodeURIComponent(d.replacedJokeId)}`}
            className="text-accent underline decoration-accent/40 hover:decoration-accent"
            onClick={(e) => e.stopPropagation()}
          >
            {d.replacedJokeId}
          </Link>
          .
        </p>
      ) : (
        <p className="mt-1 pl-5 font-mono text-[11px] text-lo leading-relaxed">{d.subtitle}</p>
      )}
    </button>
  )
}
