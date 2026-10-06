import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDelta, formatNumber, formatTime } from "@/lib/format-number";
import type { Reading } from "./metrics-api";

type TileProps = {
  title: string;
  unit: string;
  value: number | null;
  previous: number | null;
  digits: number;
  color: string;
  at: number | null;
  alert?: boolean;
};

function Tile({ title, unit, value, previous, digits, color, at, alert }: TileProps) {
  const delta = formatDelta(value, previous, digits);
  return (
    <Card role="group" aria-label={title}>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <span
            className="inline-block size-2.5 rounded-full"
            style={{ background: color }}
            aria-hidden="true"
          />
          {title}
        </CardTitle>
        {alert && (
          <Badge variant="destructive" className="gap-1">
            <AlertTriangle className="size-3" aria-hidden="true" />
            Alerte gaz
          </Badge>
        )}
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tabular-nums">
          {formatNumber(value, digits)}{" "}
          <span className="text-muted-foreground text-base font-normal">{unit}</span>
        </p>
        <p className="text-muted-foreground mt-1 text-xs tabular-nums">
          {delta ? (
            <span>
              {delta} {unit}{" "}
            </span>
          ) : null}
          {at ? <span>à {formatTime(at)}</span> : <span>En attente de mesure</span>}
        </p>
      </CardContent>
    </Card>
  );
}

export function MetricTiles({
  latest,
  previous,
}: {
  latest: Reading | null;
  previous: Reading | null;
}) {
  const at = latest ? Date.parse(latest.recorded_at) : null;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Tile
        title="Température"
        unit="°C"
        digits={1}
        color="var(--metric-temperature)"
        at={at}
        value={latest?.temperature_c ?? null}
        previous={previous?.temperature_c ?? null}
      />
      <Tile
        title="Humidité"
        unit="%"
        digits={0}
        color="var(--metric-humidity)"
        at={at}
        value={latest?.humidity_pct ?? null}
        previous={previous?.humidity_pct ?? null}
      />
      <Tile
        title="Gaz"
        unit="ppm"
        digits={0}
        color="var(--metric-gas)"
        at={at}
        alert={latest?.gas_alert}
        value={latest?.gas_ppm ?? null}
        previous={previous?.gas_ppm ?? null}
      />
    </div>
  );
}
