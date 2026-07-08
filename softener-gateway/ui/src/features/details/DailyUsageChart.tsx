import { Box, Group, Text } from "@mantine/core";

import { SectionCard } from "../../shared/components/SectionCard";
import type { DailyUsageProfile } from "../../shared/types/softener";
import { formatNumber } from "../../shared/utils/format";

type DailyUsageChartProps = {
  profile: DailyUsageProfile;
  unit: string;
};

type DayKey = keyof DailyUsageProfile;

type ChartPoint = {
  average: number;
  deviation: number;
  index: number;
  label: string;
  lower: number;
  upper: number;
  x: number;
  y: number;
  yLower: number;
  yUpper: number;
};

const DAYS: { key: DayKey; label: string }[] = [
  { key: "day_1", label: "Day 1" },
  { key: "day_2", label: "Day 2" },
  { key: "day_3", label: "Day 3" },
  { key: "day_4", label: "Day 4" },
  { key: "day_5", label: "Day 5" },
  { key: "day_6", label: "Day 6" },
  { key: "day_7", label: "Day 7" },
];

const CHART_WIDTH = 360;
const CHART_HEIGHT = 170;
const CHART_PADDING = {
  bottom: 42,
  left: 12,
  right: 42,
  top: 12,
};

export function DailyUsageChart({ profile, unit }: DailyUsageChartProps) {
  const values = DAYS.map((day, index) => {
    const item = profile[day.key];
    if (!isNumber(item?.average)) {
      return null;
    }

    const deviation = isNumber(item?.deviation) ? Math.max(0, item.deviation) : 0;
    return {
      average: item.average,
      deviation,
      index,
      label: day.label,
      lower: Math.max(0, item.average - deviation),
      upper: item.average + deviation,
    };
  }).filter((item): item is Omit<ChartPoint, "x" | "y" | "yLower" | "yUpper"> => item !== null);

  if (values.length < 2) {
    return (
      <SectionCard title="Daily usage profile">
        <Text c="dimmed" size="sm">
          Not enough daily usage data.
        </Text>
      </SectionCard>
    );
  }

  const maxValue = Math.max(1, ...values.map((point) => point.upper));
  const xScale = (index: number) =>
    CHART_PADDING.left +
    (index / (DAYS.length - 1)) * (CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right);
  const yScale = (value: number) =>
    CHART_HEIGHT -
    CHART_PADDING.bottom -
    (value / maxValue) * (CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom);

  const points: ChartPoint[] = values.map((point) => ({
    ...point,
    x: xScale(point.index),
    y: yScale(point.average),
    yLower: yScale(point.lower),
    yUpper: yScale(point.upper),
  }));

  const linePath = pathFromPoints(points.map((point) => [point.x, point.y]));
  const areaPath = [
    pathFromPoints(points.map((point) => [point.x, point.yUpper])),
    ...[...points]
      .reverse()
      .map((point, index) => `${index === 0 ? "L" : "L"} ${point.x.toFixed(2)} ${point.yLower.toFixed(2)}`),
    "Z",
  ].join(" ");

  return (
    <SectionCard title="Daily usage profile">
      <Box className="daily-usage-chart">
        <svg
          aria-label="Daily usage profile chart"
          className="daily-usage-chart__svg"
          role="img"
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        >
          {[0, 0.5, 1].map((ratio) => {
            const y = yScale(maxValue * ratio);
            const label = formatNumber(maxValue * ratio, undefined, 0);
            return (
              <g key={ratio}>
                <line
                  className="daily-usage-chart__grid"
                  x1={CHART_PADDING.left}
                  x2={CHART_WIDTH - CHART_PADDING.right}
                  y1={y}
                  y2={y}
                />
                <text
                  className="daily-usage-chart__scale-label"
                  textAnchor="start"
                  x={CHART_WIDTH - CHART_PADDING.right + 8}
                  y={y + 4}
                >
                  {label}
                </text>
              </g>
            );
          })}

          <path className="daily-usage-chart__area" d={areaPath} />
          <path className="daily-usage-chart__line" d={linePath} />

          {points.map((point) => (
            <circle className="daily-usage-chart__point" cx={point.x} cy={point.y} key={point.label} r={3.2}>
              <title>
                {point.label}: {formatNumber(point.average, unit)} average, ±{formatNumber(point.deviation, unit)}
              </title>
            </circle>
          ))}

          {DAYS.map((day, index) => (
            <text
              className="daily-usage-chart__axis-label"
              key={day.key}
              textAnchor="middle"
              x={xScale(index)}
              y={CHART_HEIGHT - 24}
            >
              {index + 1}
            </text>
          ))}

          <text
            className="daily-usage-chart__axis-title daily-usage-chart__axis-title--x"
            textAnchor="middle"
            x={(CHART_WIDTH - CHART_PADDING.right + CHART_PADDING.left) / 2}
            y={CHART_HEIGHT - 7}
          >
            Days
          </text>
          <text
            className="daily-usage-chart__axis-title daily-usage-chart__axis-title--y"
            textAnchor="middle"
            transform={`rotate(90 ${CHART_WIDTH - 7} ${CHART_HEIGHT / 2})`}
            x={CHART_WIDTH - 7}
            y={CHART_HEIGHT / 2}
          >
            Usage ({unit})
          </text>
        </svg>

        <Group gap="lg" justify="center" mt={4}>
          <Group gap="xs">
            <span className="daily-usage-chart__legend-line" />
            <Text c="dimmed" size="xs">
              Average
            </Text>
          </Group>
          <Group gap="xs">
            <span className="daily-usage-chart__legend-area" />
            <Text c="dimmed" size="xs">
              Deviation
            </Text>
          </Group>
        </Group>
      </Box>
    </SectionCard>
  );
}

function pathFromPoints(points: [number, number][]): string {
  return points
    .map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
}

function isNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && !Number.isNaN(value);
}
