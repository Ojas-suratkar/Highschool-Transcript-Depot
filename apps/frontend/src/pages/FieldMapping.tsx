import { useState } from 'react';
import { Plus, GripVertical, Trash2, Pencil, Crosshair } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Card, CardContent } from '@/components/ui/card';

interface Field {
  id: string;
  name: string;
  type: string;
  extractionMethod: string;
  required: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
}

export default function FieldMapping() {
  const [fields] = useState<Field[]>([
    {
      id: '1',
      name: 'Student Name',
      type: 'text',
      extractionMethod: 'ocr',
      required: true,
      x: 100,
      y: 50,
      width: 200,
      height: 30,
    },
  ]);

  const columns: ColumnDef<Field>[] = [
    {
      header: '',
      accessor: () => <GripVertical className="h-4 w-4 text-muted-foreground cursor-move" />,
    },
    { header: 'Field Name', accessor: 'name' },
    {
      header: 'Type',
      accessor: (row) => <Badge variant="outline">{row.type}</Badge>,
    },
    {
      header: 'Extraction Method',
      accessor: (row) => <Badge variant="secondary">{row.extractionMethod}</Badge>,
    },
    {
      header: 'Required',
      accessor: (row) => (row.required ? '✓' : '—'),
    },
    {
      header: 'Position',
      accessor: (row) => `${row.x}, ${row.y}`,
    },
    {
      header: 'Size',
      accessor: (row) => `${row.width} × ${row.height}`,
    },
    {
      header: 'Actions',
      accessor: () => (
        <div className="flex gap-1">
          <Button size="icon" variant="ghost">
            <Pencil className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost">
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PageHeader
          title="Field Mapping"
          subtitle="Define extraction field regions for templates"
        />
        <div className="flex items-center gap-4">
          <Badge variant="outline">{fields.length} Fields</Badge>
          <Badge variant="outline">{fields.filter((f) => f.required).length} Required</Badge>
          <Button variant="outline">Reset</Button>
          <Button>Save Mappings</Button>
        </div>
      </div>

      <Tabs defaultValue="definitions" className="space-y-4">
        <TabsList>
          <TabsTrigger value="definitions">Field Definitions</TabsTrigger>
          <TabsTrigger value="visual">Visual Editor</TabsTrigger>
          <TabsTrigger value="test">Test Extraction</TabsTrigger>
        </TabsList>

        <TabsContent value="definitions">
          <Card>
            <CardContent className="pt-6">
              <div className="flex justify-between mb-4">
                <h3 className="font-semibold">Field Definitions</h3>
                <Button>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Field
                </Button>
              </div>
              <DataTable
                columns={columns}
                data={fields}
                keyExtractor={(row) => row.id}
                emptyMessage="No fields defined"
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="visual">
          <Card>
            <CardContent className="pt-6">
              <div className="flex justify-between mb-4">
                <h3 className="font-semibold">Visual Field Editor</h3>
                <Button>
                  <Crosshair className="h-4 w-4 mr-2" />
                  Draw Region
                </Button>
              </div>
              <div className="border-2 border-dashed rounded-lg h-[600px] relative bg-muted/20 flex items-center justify-center">
                <p className="text-muted-foreground">
                  Template preview with field overlay regions
                </p>
                {/* Field regions would be rendered here */}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="test">
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <h3 className="font-semibold mb-4">Upload Test Transcript</h3>
                  <div className="border-2 border-dashed rounded-lg p-12 text-center">
                    <p className="text-muted-foreground">
                      Drop a test transcript here
                    </p>
                  </div>
                  <Button className="w-full mt-4">Run Test</Button>
                </div>
                <div>
                  <h3 className="font-semibold mb-4">Extraction Results</h3>
                  <div className="space-y-2">
                    {fields.map((field) => (
                      <div key={field.id} className="border rounded-lg p-3">
                        <p className="text-sm font-medium">{field.name}</p>
                        <p className="text-sm text-muted-foreground">
                          Waiting for test...
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

