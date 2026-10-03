import type { Vehicle } from "../types";

interface VehicleSelectorProps {
  vehicles: Vehicle[];
  value: string;
  customDepth: string;
  disabled: boolean;
  onVehicleChange: (value: string) => void;
  onCustomDepthChange: (value: string) => void;
}

function label(vehicle: Vehicle): string {
  return vehicle.id.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function VehicleSelector(props: VehicleSelectorProps) {
  return (
    <div className="field-group">
      <label htmlFor="vehicle">Vehicle</label>
      <select id="vehicle" value={props.value} disabled={props.disabled} onChange={(event) => props.onVehicleChange(event.target.value)}>
        {props.vehicles.map((vehicle) => (
          <option key={vehicle.id} value={vehicle.id}>
            {label(vehicle)} — {vehicle.safe_depth_cm} cm
          </option>
        ))}
        <option value="custom">Custom clearance</option>
      </select>
      {props.value === "custom" && (
        <label className="custom-depth" htmlFor="custom-depth">
          Safe depth (cm)
          <input
            id="custom-depth"
            type="number"
            min="1"
            inputMode="decimal"
            placeholder="e.g. 20"
            value={props.customDepth}
            onChange={(event) => props.onCustomDepthChange(event.target.value)}
          />
        </label>
      )}
    </div>
  );
}
