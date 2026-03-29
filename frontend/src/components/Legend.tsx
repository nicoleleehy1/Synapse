// Maps entity types to chart variables
const TYPES: { label: string; bg: string; text: string }[] = [
  { label: 'Person',       bg: '#1a1a1a', text: '#ffffff' },
  { label: 'Organization', bg: '#404040', text: '#ffffff' },
  { label: 'Location',     bg: '#404040', text: '#ffffff' },
  { label: 'Technology',   bg: '#525252', text: '#ffffff' },
  { label: 'Event',        bg: '#525252', text: '#ffffff' },
  { label: 'Concept',      bg: '#a3a3a3', text: '#0a0a0a' },
  { label: 'Product',      bg: '#a3a3a3', text: '#0a0a0a' },
  { label: 'Other',        bg: '#d4d4d4', text: '#0a0a0a' },
]

export function Legend() {
  return (
    <div className="absolute bottom-5 left-5 bg-background border border-border rounded p-3 z-10">
      <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-2.5">
        Entity types
      </p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {TYPES.map((t) => (
          <div key={t.label} className="flex items-center gap-2">
            <div
              className="w-2.5 h-1.5 rounded-sm shrink-0"
              style={{ backgroundColor: t.bg }}
            />
            <span className="text-xs text-chart-3">{t.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
