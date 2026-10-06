import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatNumber, formatTime } from "@/lib/format-number";
import type { MetricPoint } from "./metrics-api";

export function ReadingsTable({ points, bucketed }: { points: MetricPoint[]; bucketed: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{bucketed ? "Intervalle" : "Heure"}</TableHead>
          <TableHead className="text-right">Température (°C)</TableHead>
          <TableHead className="text-right">Humidité (%)</TableHead>
          <TableHead className="text-right">Gaz (mV)</TableHead>
          <TableHead>Alerte</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {[...points].reverse().map((p) => (
          <TableRow key={p.time}>
            <TableCell>{formatTime(p.time)}</TableCell>
            <TableCell className="text-right tabular-nums">
              {formatNumber(p.temperature, 1)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(p.humidity, 0)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatNumber(p.gas, 0)}</TableCell>
            <TableCell>{p.gasAlert ? "Alerte gaz" : "–"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
