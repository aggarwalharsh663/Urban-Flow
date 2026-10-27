import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function TrafficChart({ data, colors }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 10, right: 8, left: -10, bottom: 0 }} barGap={6}>
        <CartesianGrid stroke="var(--grid-line)" vertical={false} />
        <XAxis
          dataKey="direction"
          tick={{ fill: "var(--ink)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          dy={9}
        />
        <YAxis
          domain={[0, (dataMax) => Math.max(60, Math.ceil(((dataMax || 0) * 1.15) / 10) * 10)]}
          tick={{ fill: "var(--ink-soft)", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            background: "var(--card)",
            border: "3px solid var(--ink)",
            borderRadius: 0,
            color: "var(--ink)",
            fontSize: 12,
          }}
          cursor={{ fill: "rgba(255,255,255,.03)" }}
        />
        <Bar dataKey="vehicles" name="Vehicles" radius={0} maxBarSize={24}>
          {data.map((entry) => (
            <Cell
              key={entry.direction}
              fill={colors[entry.direction]}
              stroke="var(--ink)"
              strokeWidth={2}
            />
          ))}
        </Bar>
        <Bar dataKey="green" name="Green seconds" fill="var(--ink-soft)" radius={0} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}
