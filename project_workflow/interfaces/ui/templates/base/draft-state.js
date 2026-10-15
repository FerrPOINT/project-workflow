/** Tracks acknowledgements, not requests: an old response cannot clean a newer edit. */
/** @param {() => void} [onChange] @returns {import("./draft-types").DraftTracker} */
export function createDraftTracker(onChange = () => {}) {
  let revision = 0, savedRevision = 0
  const unknown = new Set()
  const pending = new Set()
  return {
    edit() { revision++; onChange(); return revision },
    beginSave() {
      if (unknown.size) throw new Error('Read back the previous save before retrying.')
      const ticket = { revision }
      pending.add(ticket)
      onChange()
      return ticket
    },
    finishSave(ticket, outcome) {
      if (!pending.delete(ticket)) return
      if (outcome === 'saved') savedRevision = Math.max(savedRevision, ticket.revision)
      if (outcome === 'unknown') unknown.add(ticket)
      onChange()
    },
    /** The owner resolves an uncertain write by comparing its submitted payload with readback. */
    reconcile(ticket, saved) {
      if (!unknown.delete(ticket)) return
      if (saved) savedRevision = Math.max(savedRevision, ticket.revision)
      onChange()
    },
    get dirty() { return revision !== savedRevision || pending.size > 0 || unknown.size > 0 },
    get pending() { return pending.size > 0 },
    get uncertain() { return unknown.size > 0 },
  }
}
