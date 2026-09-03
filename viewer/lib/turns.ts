/** Group trace / librarian-step rows by turn for the archive and live feed. */

export type TriggerType =
  | 'cold_open'
  | 'user_request'
  | 'set_continuation'
  | 'reroll'
  | 'barge_in_recovery'
  | 'query_slot'

export interface TurnFields {
  trigger_type?: string | null
  trigger_text?: string | null
  turn_id?: string | null
  turn_index?: number | null
}

export interface TurnGroup<T extends TurnFields> {
  key: string
  turn_id: string | null
  turn_index: number | null
  trigger_type: string | null
  trigger_text: string | null
  items: T[]
}

function metaOf<T extends TurnFields>(item: T): {
  inputs?: Record<string, unknown>
  payload?: Record<string, unknown>
  kind?: string
} {
  const rec = item as T & {
    inputs?: Record<string, unknown>
    payload?: Record<string, unknown>
    kind?: string
  }
  return rec
}

export function groupByTurn<T extends TurnFields>(items: T[]): TurnGroup<T>[] {
  const ungrouped: T[] = []
  const buckets = new Map<string, T[]>()
  const order: string[] = []

  for (const item of items) {
    const id = item.turn_id
    if (!id) {
      ungrouped.push(item)
      continue
    }
    if (!buckets.has(id)) {
      buckets.set(id, [])
      order.push(id)
    }
    buckets.get(id)!.push(item)
  }

  const groups: TurnGroup<T>[] = []
  if (ungrouped.length > 0) {
    const first = ungrouped[0]
    groups.push({
      key: '__none__',
      turn_id: null,
      turn_index: first.turn_index ?? null,
      trigger_type: first.trigger_type ?? null,
      trigger_text: first.trigger_text ?? null,
      items: ungrouped,
    })
  }

  const indexed = order.map((id) => {
    const groupedItems = buckets.get(id)!
    const first = groupedItems[0]
    return {
      key: id,
      turn_id: id,
      turn_index: first.turn_index ?? null,
      trigger_type: first.trigger_type ?? null,
      trigger_text: first.trigger_text ?? null,
      items: groupedItems,
    }
  })
  indexed.sort((a, b) => (a.turn_index ?? 0) - (b.turn_index ?? 0))
  groups.push(...indexed)
  return groups
}

function replacedJokeId<T extends TurnFields>(group: TurnGroup<T>): string | null {
  for (const item of group.items) {
    const m = metaOf(item)
    const fromInputs = m.inputs?.original_joke_id
    const fromPayload = m.payload?.original_joke_id
    const id = (typeof fromInputs === 'string' && fromInputs) || (typeof fromPayload === 'string' && fromPayload)
    if (id) return id
  }
  return null
}

function generationMeta<T extends TurnFields>(group: TurnGroup<T>): {
  position?: number
  topic?: string
  slotCount?: number
  following?: string
} {
  for (const item of group.items) {
    const m = metaOf(item)
    const bag = { ...(m.inputs ?? {}), ...(m.payload ?? {}) }
    if (m.kind === 'generation' || bag.topic != null || bag.set_position != null || bag.slot_idx != null) {
      const pos = (bag.set_position as number | undefined) ?? (
        typeof bag.slot_idx === 'number' ? bag.slot_idx + 1 : undefined
      )
      const total = bag.slot_count as number | undefined
      const topic = typeof bag.topic === 'string' ? bag.topic : undefined
      return { position: pos, topic, slotCount: total, following: topic }
    }
  }
  return {}
}

export function describeTurn<T extends TurnFields>(group: TurnGroup<T>): {
  kicker: string
  subtitle: string
  quoted: boolean
  replacedJokeId: string | null
} {
  const idx = group.turn_index
  const typeLabel = group.trigger_type ?? 'unrecorded'
  const kicker = idx != null ? `TURN ${idx}  ·  ${typeLabel}` : `TURN  ·  ${typeLabel}`
  const replaced = group.trigger_type === 'reroll' ? replacedJokeId(group) : null

  if (group.trigger_type === 'cold_open') {
    return { kicker, subtitle: 'Host opened unprompted.', quoted: false, replacedJokeId: replaced }
  }
  if (group.trigger_type === 'set_continuation') {
    const g = generationMeta(group)
    const bit = g.position != null
      ? g.slotCount != null
        ? `Bit ${g.position} of ${g.slotCount}`
        : `Bit ${g.position}`
      : 'Next bit of the planned set'
    const follow = g.following ? `, following "${g.following}"` : ''
    return { kicker, subtitle: `${bit}${follow}.`, quoted: false, replacedJokeId: replaced }
  }
  if (group.trigger_type === 'barge_in_recovery') {
    return {
      kicker,
      subtitle: 'Host resumed after being interrupted.',
      quoted: false,
      replacedJokeId: replaced,
    }
  }
  if (group.trigger_type === 'reroll') {
    return {
      kicker,
      subtitle: replaced ? `Replacing joke ${replaced}.` : 'Listener rejected the previous joke.',
      quoted: false,
      replacedJokeId: replaced,
    }
  }
  if (group.trigger_text) {
    return { kicker, subtitle: group.trigger_text, quoted: true, replacedJokeId: replaced }
  }
  if (group.trigger_type === 'query_slot') {
    return { kicker, subtitle: 'Request came through the Query Slot.', quoted: false, replacedJokeId: replaced }
  }
  if (group.trigger_type === 'user_request') {
    return { kicker, subtitle: 'Listener asked for something specific.', quoted: false, replacedJokeId: replaced }
  }
  if (!group.trigger_type) {
    return {
      kicker: 'TURN  ·  unrecorded',
      subtitle: 'No trigger was stored for these steps (filed before turns).',
      quoted: false,
      replacedJokeId: null,
    }
  }
  return { kicker, subtitle: typeLabel, quoted: false, replacedJokeId: replaced }
}
