import { Badge, Group, ScrollArea, Table, Text } from "@mantine/core";

import type { DiagnosticRow } from "../../shared/types/softener";
import { formatUpdatedAt } from "../../shared/utils/format";
import { formatDiagnosticValue } from "../../shared/utils/normalize";

type RawDataTableProps = {
  rows: DiagnosticRow[];
  updatedAt?: string;
};

export function RawDataTable({ rows, updatedAt }: RawDataTableProps) {
  if (rows.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        No data for the selected filter.
      </Text>
    );
  }

  return (
    <ScrollArea>
      <Table className="raw-table" highlightOnHover verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Parameter</Table.Th>
            <Table.Th>Value</Table.Th>
            <Table.Th>Writable</Table.Th>
            <Table.Th>Updated</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.key}>
              <Table.Td>
                <Group gap="xs">
                  <Text fw={600} size="sm">
                    {titleCase(row.label)}
                  </Text>
                  {row.changed ? (
                    <Badge color="waterBlue" radius="sm" size="xs" variant="light">
                      changed
                    </Badge>
                  ) : null}
                </Group>
                <Text c="dimmed" size="xs">
                  {row.key}
                </Text>
              </Table.Td>
              <Table.Td>{formatDiagnosticValue(row)}</Table.Td>
              <Table.Td>
                <Badge color={row.writable ? "green" : "gray"} radius="sm" variant="light">
                  {row.writable ? "yes" : "no"}
                </Badge>
              </Table.Td>
              <Table.Td>{formatUpdatedAt(row.timestamp ?? updatedAt)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}

function titleCase(value: string): string {
  return value
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
