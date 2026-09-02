import type { JokeSummary, SelectionPath, TreeData } from './types'

/** Seed script rows: curated provenance and set_id.set = seed-set. */
export function isSeedJoke(joke: JokeSummary): boolean {
  return joke.set === 'seed-set' || joke.source === 'curated'
}

/** Concurrency-test cabinet (RaceCab / set_default Thread N jokes). */
export function isTestFixtureJoke(joke: JokeSummary): boolean {
  return joke.set === 'set_default'
}

export function isHiddenFromBrowse(joke: JokeSummary): boolean {
  return isSeedJoke(joke) || isTestFixtureJoke(joke)
}

export function treeWithoutSeedJokes(tree: TreeData): TreeData {
  return {
    cabinets: tree.cabinets
      .filter((cab) => cab.label !== 'RaceCab')
      .map((cab) => ({
        ...cab,
        drawers: cab.drawers
          .map((drw) => ({
            ...drw,
            files: drw.files
              .map((fil) => {
                const jokes = (fil.jokes ?? []).filter((j) => !isHiddenFromBrowse(j))
                return { ...fil, jokes, joke_count: jokes.length }
              })
              .filter((fil) => fil.joke_count > 0),
          }))
          .filter((drw) => drw.files.length > 0),
      }))
      .filter((cab) => cab.drawers.length > 0),
  }
}

export function pickFirstArchiveJoke(
  tree: TreeData,
): { id: string; path: SelectionPath } | null {
  const scan = (skipRace: boolean) => {
    for (const cab of tree.cabinets) {
      if (skipRace && cab.label === 'RaceCab') continue
      for (const drw of cab.drawers) {
        for (const fil of drw.files) {
          const first = (fil.jokes ?? []).find((j) => !isHiddenFromBrowse(j)) ?? null
          if (first) {
            return {
              id: first.id,
              path: { cabinet: cab.label, drawer: drw.label, file: fil.label },
            }
          }
        }
      }
    }
    return null
  }
  return scan(true) ?? scan(false)
}
