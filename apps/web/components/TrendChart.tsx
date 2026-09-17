'use client';

/**
 * TrendChart — SVG inline, nol dependency baru (UI/UX ide #8).
 *
 * Menampilkan seri angka NYATA dari `/observability/trend`. Aturan jujur:
 * - Titik yang `null` (pembacaan gagal) DIGAMBAR SEBAGAI CELAH, bukan 0.
 * - Bila tidak ada satu pun titik valid, tampilkan pesan kosong — bukan
 *   garis datar palsu.
 * - Sumbu Y diberi label nilai min/max nyata dari data, bukan skala karangan.
 */

type TrendChartProps = {
  /** Titik data berurutan (terlama → terbaru). `null` = celah. */
  values: (number | null)[];
  /** Label aksesibel + judul kecil di atas grafik. */
  label: string;
  /** Format nilai untuk label sumbu + tooltip (mis. pemisah ribuan). */
  format?: (value: number) => string;
  /** Warna garis; default memakai token primary. */
  color?: string;
  height?: number;
};

const DEFAULT_HEIGHT = 120;
const PAD_X = 8;
const PAD_TOP = 10;
const PAD_BOTTOM = 18;

function buildPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return '';
  return points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');
}

export default function TrendChart({
  values,
  label,
  format = (v) => String(Math.round(v)),
  color = 'var(--primary)',
  height = DEFAULT_HEIGHT,
}: TrendChartProps) {
  const valid = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));

  if (valid.length < 2) {
    return (
      <div className="trendChartEmpty" role="img" aria-label={`${label}: belum ada data`}>
        <span>Belum ada cukup sampel untuk digambar ({valid.length} dari 2 minimum).</span>
      </div>
    );
  }

  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const span = max - min || Math.abs(max) || 1;
  const width = 600; // viewBox units; SVG scales via CSS width: 100%
  const innerW = width - PAD_X * 2;
  const innerH = height - PAD_TOP - PAD_BOTTOM;

  // Celah: nilai null memutus garis. Kita bangun beberapa sub-path terpisah.
  const segments: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [];
  values.forEach((v, i) => {
    const x = PAD_X + (values.length === 1 ? 0 : (i / (values.length - 1)) * innerW);
    if (typeof v === 'number' && Number.isFinite(v)) {
      const y = PAD_TOP + innerH - ((v - min) / span) * innerH;
      current.push({ x, y });
    } else if (current.length > 0) {
      segments.push(current);
      current = [];
    }
  });
  if (current.length > 0) segments.push(current);

  const last = valid[valid.length - 1];
  const first = valid[0];
  const delta = last - first;

  return (
    <div className="trendChart">
      <div className="trendChartHead">
        <span className="trendChartLabel">{label}</span>
        <span className="trendChartMeta">
          {format(first)} → {format(last)}{' '}
          <strong className={delta >= 0 ? 'trendUp' : 'trendDown'}>
            ({delta >= 0 ? '+' : ''}
            {format(delta)})
          </strong>
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: ${valid.length} titik, dari ${format(min)} sampai ${format(max)}`}
      >
        {/* Garis bantu min/max nyata */}
        <line x1={PAD_X} y1={PAD_TOP} x2={width - PAD_X} y2={PAD_TOP} className="trendGrid" />
        <line
          x1={PAD_X}
          y1={PAD_TOP + innerH}
          x2={width - PAD_X}
          y2={PAD_TOP + innerH}
          className="trendGrid"
        />
        {segments.map((seg, i) => (
          <path key={i} d={buildPath(seg)} fill="none" stroke={color} strokeWidth={2} />
        ))}
        {/* Penanda celah: titik kecil di posisi data yang gagal dibaca */}
        {values.map((v, i) =>
          v === null ? (
            <circle
              key={`gap-${i}`}
              cx={PAD_X + (values.length === 1 ? 0 : (i / (values.length - 1)) * innerW)}
              cy={PAD_TOP + innerH}
              r={1.5}
              className="trendGapDot"
            />
          ) : null,
        )}
      </svg>
      <div className="trendChartAxis">
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
    </div>
  );
}
