import { Card, Skeleton, Stack } from "@mantine/core";

type LoadingStateProps = {
  rows?: number;
};

export function LoadingState({ rows = 4 }: LoadingStateProps) {
  return (
    <Card className="section-card" padding="lg" radius="xl" withBorder>
      <Stack gap="sm">
        {Array.from({ length: rows }, (_, index) => (
          <Skeleton height={index === 0 ? 34 : 18} key={index} radius="md" />
        ))}
      </Stack>
    </Card>
  );
}
