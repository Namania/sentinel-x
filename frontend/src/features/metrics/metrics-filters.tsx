import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { RANGE_LABELS, RANGES, type Device, type Range } from "./metrics-api";

export type View = "charts" | "table";

type Props = {
  devices: Device[];
  deviceId: string | null;
  onDeviceChange: (deviceId: string) => void;
  range: Range;
  onRangeChange: (range: Range) => void;
  live: boolean;
  onLiveChange: (live: boolean) => void;
  view: View;
  onViewChange: (view: View) => void;
};

export function MetricsFilters(props: Props) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-2">
        <Label htmlFor="metrics-device">Appareil</Label>
        <Select value={props.deviceId ?? undefined} onValueChange={props.onDeviceChange}>
          <SelectTrigger id="metrics-device" className="w-44">
            <SelectValue placeholder="Appareil" />
          </SelectTrigger>
          <SelectContent>
            {props.devices.map((d) => (
              <SelectItem key={d.device_id} value={d.device_id}>
                {d.device_id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <ToggleGroup
        type="single"
        value={props.range}
        onValueChange={(value) => value && props.onRangeChange(value as Range)}
        aria-label="Plage"
        variant="outline"
      >
        {RANGES.map((r) => (
          <ToggleGroupItem key={r} value={r}>
            {RANGE_LABELS[r]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="flex items-center gap-2">
        <Switch id="metrics-live" checked={props.live} onCheckedChange={props.onLiveChange} />
        <Label htmlFor="metrics-live">Direct</Label>
      </div>
      <ToggleGroup
        type="single"
        value={props.view}
        onValueChange={(value) => value && props.onViewChange(value as View)}
        aria-label="Affichage"
        variant="outline"
        className="ml-auto"
      >
        <ToggleGroupItem value="charts">Graphiques</ToggleGroupItem>
        <ToggleGroupItem value="table">Tableau</ToggleGroupItem>
      </ToggleGroup>
    </div>
  );
}
