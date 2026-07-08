import { SimpleGrid } from "@mantine/core";

import { DataValue } from "../../shared/components/DataValue";
import { SectionCard } from "../../shared/components/SectionCard";

type DataGroupItem = {
  label: string;
  value?: string | number | boolean | null;
};

type DataGroupCardProps = {
  description?: string;
  items: DataGroupItem[];
  title: string;
};

export function DataGroupCard({ description, items, title }: DataGroupCardProps) {
  return (
    <SectionCard description={description} title={title}>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
        {items.map((item) => (
          <DataValue key={item.label} label={item.label} value={item.value} />
        ))}
      </SimpleGrid>
    </SectionCard>
  );
}
