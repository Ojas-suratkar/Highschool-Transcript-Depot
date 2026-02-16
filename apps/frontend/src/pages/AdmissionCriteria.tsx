import { useState } from 'react';
import { Save, Plus, Trash2, GripVertical } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { TermSelector } from '@/components/shared/TermSelector';
import { ValueTypeSelector, ValueType } from '@/components/shared/ValueTypeSelector';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { PageHeader } from '@/components/shared/PageHeader';
import { toast } from 'sonner';

interface AGCourse {
  id: string;
  label: string;
  years: number;
  valueType: ValueType;
  minValue: string;
}

interface Condition {
  id: string;
  name: string;
  type: string;
  operator: string;
  valueType: ValueType;
  value: string;
  auto: boolean;
}

interface CriteriaGroup {
  id: string;
  connector: 'AND' | 'OR';
  term: string;
  conditions: Condition[];
}

export default function AdmissionCriteria() {
  const [gpaMin, setGpaMin] = useState(2.5);
  const [gpaMax, setGpaMax] = useState(4.0);
  const [selectedTerm, setSelectedTerm] = useState('');

  const [agCourses, setAgCourses] = useState<AGCourse[]>([
    { id: 'a', label: 'A - History/Social Science', years: 2, valueType: 'grade', minValue: 'C' },
    { id: 'b', label: 'B - English', years: 4, valueType: 'grade', minValue: 'C' },
    { id: 'c', label: 'C - Mathematics', years: 3, valueType: 'grade', minValue: 'C' },
    { id: 'd', label: 'D - Laboratory Science', years: 2, valueType: 'grade', minValue: 'C' },
    { id: 'e', label: 'E - Language Other Than English', years: 2, valueType: 'grade', minValue: 'C' },
    { id: 'f', label: 'F - Visual & Performing Arts', years: 1, valueType: 'grade', minValue: 'C' },
    { id: 'g', label: 'G - College Preparatory Elective', years: 1, valueType: 'grade', minValue: 'C' },
  ]);

  const [groups, setGroups] = useState<CriteriaGroup[]>([]);

  const handleQuickSelect = (value: number) => {
    setGpaMin(value);
  };

  const handleAddGroup = () => {
    const newGroup: CriteriaGroup = {
      id: Date.now().toString(),
      connector: 'AND',
      term: '',
      conditions: [],
    };
    setGroups([...groups, newGroup]);
  };

  const handleAddCondition = (groupId: string) => {
    setGroups(groups.map(g => {
      if (g.id === groupId) {
        return {
          ...g,
          conditions: [
            ...g.conditions,
            {
              id: Date.now().toString(),
              name: '',
              type: 'GPA',
              operator: '>=',
              valueType: 'gpa',
              value: '',
              auto: false,
            },
          ],
        };
      }
      return g;
    }));
  };

  const handleDeleteGroup = (groupId: string) => {
    setGroups(groups.filter(g => g.id !== groupId));
  };

  const handleDeleteCondition = (groupId: string, conditionId: string) => {
    setGroups(groups.map(g => {
      if (g.id === groupId) {
        return {
          ...g,
          conditions: g.conditions.filter(c => c.id !== conditionId),
        };
      }
      return g;
    }));
  };

  const handleSave = () => {
    const criteria = {
      gpa: { min: gpaMin, max: gpaMax },
      agCourses,
      groups,
      term: selectedTerm,
    };
    localStorage.setItem('admissionCriteria', JSON.stringify(criteria));
    toast.success('Admission criteria saved successfully');
  };

  const generatePreview = () => {
    let preview = `GPA: ${gpaMin.toFixed(2)} - ${gpaMax.toFixed(2)}\n\n`;
    preview += 'A-G Requirements:\n';
    agCourses.forEach(course => {
      preview += `  ${course.label}: ${course.years} years, min: ${course.minValue}\n`;
    });
    if (groups.length > 0) {
      preview += '\nCustom Criteria:\n';
      groups.forEach((group, idx) => {
        preview += `  Group ${idx + 1} (${group.connector}):\n`;
        group.conditions.forEach(cond => {
          preview += `    ${cond.name} ${cond.operator} ${cond.value}\n`;
        });
      });
    }
    return preview;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Institutional"
        subtitle="Configure institution-level admission requirements"
      />

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Card 1: GPA Requirements */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">GPA Requirements</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6 pt-6">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium">GPA Range</Label>
                <span className="text-lg font-semibold text-primary">
                  {gpaMin.toFixed(2)} - {gpaMax.toFixed(2)}
                </span>
              </div>

              <div className="space-y-3 px-2">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Minimum GPA</Label>
                  <input
                    type="range"
                    min="0"
                    max="4"
                    step="0.01"
                    value={gpaMin}
                    onChange={(e) => setGpaMin(Math.min(parseFloat(e.target.value), gpaMax))}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Maximum GPA</Label>
                  <input
                    type="range"
                    min="0"
                    max="4"
                    step="0.01"
                    value={gpaMax}
                    onChange={(e) => setGpaMax(Math.max(parseFloat(e.target.value), gpaMin))}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex-1">
                <Label className="text-xs text-muted-foreground mb-1 block">Min</Label>
                <Input
                  type="number"
                  min="0"
                  max="4"
                  step="0.01"
                  value={gpaMin}
                  onChange={(e) => setGpaMin(Math.min(parseFloat(e.target.value) || 0, gpaMax))}
                  className="w-20 text-center font-medium"
                />
              </div>
              <div className="flex-1">
                <Label className="text-xs text-muted-foreground mb-1 block">Max</Label>
                <Input
                  type="number"
                  min="0"
                  max="4"
                  step="0.01"
                  value={gpaMax}
                  onChange={(e) => setGpaMax(Math.max(parseFloat(e.target.value) || 0, gpaMin))}
                  className="w-20 text-center font-medium"
                />
              </div>
            </div>

            <div>
              <Label className="text-xs text-muted-foreground mb-2 block">Quick Select Minimum</Label>
              <div className="flex gap-2">
                <Button
                  variant={gpaMin === 2.5 ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => handleQuickSelect(2.5)}
                  className="flex-1"
                >
                  2.5
                </Button>
                <Button
                  variant={gpaMin === 3.0 ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => handleQuickSelect(3.0)}
                  className="flex-1"
                >
                  3.0
                </Button>
                <Button
                  variant={gpaMin === 3.5 ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => handleQuickSelect(3.5)}
                  className="flex-1"
                >
                  3.5
                </Button>
                <Button
                  variant={gpaMin === 4.0 ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => handleQuickSelect(4.0)}
                  className="flex-1"
                >
                  4.0
                </Button>
              </div>
            </div>

            <div className="border-t pt-4 bg-muted/20 -mx-6 px-6 -mb-6 pb-6 rounded-b-lg">
              <TermSelector
                value={selectedTerm}
                onValueChange={setSelectedTerm}
                label="Apply to Term"
                showAddButton={true}
              />
            </div>
          </CardContent>
        </Card>

        {/* Card 2: A-G Course Type Criteria */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">A-G Course Type Criteria</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {agCourses.map((course) => (
              <div key={course.id} className="flex items-center gap-3 p-2 rounded-md hover:bg-muted/30 transition-colors">
                <div className="w-56">
                  <Input
                    value={course.label}
                    onChange={(e) => {
                      const newCourses = agCourses.map(c =>
                        c.id === course.id ? { ...c, label: e.target.value } : c
                      );
                      setAgCourses(newCourses);
                    }}
                    className="text-sm font-medium"
                  />
                </div>
                <Input
                  type="number"
                  min="0"
                  max="8"
                  value={course.years}
                  onChange={(e) => {
                    const newCourses = agCourses.map(c =>
                      c.id === course.id ? { ...c, years: parseInt(e.target.value) || 0 } : c
                    );
                    setAgCourses(newCourses);
                  }}
                  className="w-16 text-center"
                />
                <span className="text-sm text-muted-foreground whitespace-nowrap">years, min:</span>
                <ValueTypeSelector
                  valueType={course.valueType}
                  onValueTypeChange={(type) => {
                    const newCourses = agCourses.map(c =>
                      c.id === course.id ? { ...c, valueType: type } : c
                    );
                    setAgCourses(newCourses);
                  }}
                  value={course.minValue}
                  onValueChange={(val) => {
                    const newCourses = agCourses.map(c =>
                      c.id === course.id ? { ...c, minValue: val } : c
                    );
                    setAgCourses(newCourses);
                  }}
                  className="flex-1"
                />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Card 3: Custom Criteria Builder */}
      <Card className="shadow-sm">
        <CardHeader className="flex flex-row items-center justify-between border-b bg-muted/30">
          <CardTitle className="text-lg font-semibold">Custom Criteria Builder</CardTitle>
          <Button onClick={handleAddGroup} variant="outline" size="sm">
            <Plus className="h-4 w-4 mr-2" />
            Add Group
          </Button>
        </CardHeader>
        <CardContent className="pt-6">
          {groups.length === 0 ? (
            <div className="text-center py-12 px-4">
              <p className="text-muted-foreground text-sm">
                No custom criteria groups defined. Click "Add Group" to create one.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {groups.map((group, groupIdx) => (
                <Card key={group.id} className="border-dashed border-2 shadow-none">
                  <CardContent className="pt-6 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <GripVertical className="h-4 w-4 text-muted-foreground" />
                        <span className="font-medium">Group {groupIdx + 1}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <ToggleGroup
                          type="single"
                          value={group.connector}
                          onValueChange={(val) => {
                            if (val) {
                              setGroups(groups.map(g =>
                                g.id === group.id ? { ...g, connector: val as 'AND' | 'OR' } : g
                              ));
                            }
                          }}
                        >
                          <ToggleGroupItem value="AND">AND</ToggleGroupItem>
                          <ToggleGroupItem value="OR">OR</ToggleGroupItem>
                        </ToggleGroup>
                        <Badge>{group.term || 'No term'}</Badge>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDeleteGroup(group.id)}
                          className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>

                    <TermSelector
                      value={group.term}
                      onValueChange={(val) => {
                        setGroups(groups.map(g =>
                          g.id === group.id ? { ...g, term: val } : g
                        ));
                      }}
                      label="Term"
                      showAddButton={false}
                    />

                    <div className="space-y-2">
                      {group.conditions.map((condition, condIdx) => (
                        <div key={condition.id} className="flex items-center gap-2">
                          {condIdx > 0 && (
                            <Badge variant="outline" className="shrink-0">
                              {group.connector}
                            </Badge>
                          )}
                          <Input
                            placeholder="Name"
                            value={condition.name}
                            onChange={(e) => {
                              setGroups(groups.map(g => {
                                if (g.id === group.id) {
                                  return {
                                    ...g,
                                    conditions: g.conditions.map(c =>
                                      c.id === condition.id ? { ...c, name: e.target.value } : c
                                    ),
                                  };
                                }
                                return g;
                              }));
                            }}
                            className="w-32"
                          />
                          <Select
                            value={condition.type}
                            onValueChange={(val) => {
                              setGroups(groups.map(g => {
                                if (g.id === group.id) {
                                  return {
                                    ...g,
                                    conditions: g.conditions.map(c =>
                                      c.id === condition.id ? { ...c, type: val } : c
                                    ),
                                  };
                                }
                                return g;
                              }));
                            }}
                          >
                            <SelectTrigger className="w-40">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="GPA">GPA</SelectItem>
                              <SelectItem value="A-G">A-G</SelectItem>
                              <SelectItem value="Course Match">Course Match</SelectItem>
                              <SelectItem value="Grade Rule">Grade Rule</SelectItem>
                              <SelectItem value="Marks Rule">Marks Rule</SelectItem>
                              <SelectItem value="Document Rule">Document Rule</SelectItem>
                              <SelectItem value="Manual Review">Manual Review</SelectItem>
                              <SelectItem value="Other">Other</SelectItem>
                            </SelectContent>
                          </Select>
                          <Select
                            value={condition.operator}
                            onValueChange={(val) => {
                              setGroups(groups.map(g => {
                                if (g.id === group.id) {
                                  return {
                                    ...g,
                                    conditions: g.conditions.map(c =>
                                      c.id === condition.id ? { ...c, operator: val } : c
                                    ),
                                  };
                                }
                                return g;
                              }));
                            }}
                          >
                            <SelectTrigger className="w-32">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value=">=">&gt;=</SelectItem>
                              <SelectItem value="<=">&lt;=</SelectItem>
                              <SelectItem value="=">=</SelectItem>
                              <SelectItem value="between">between</SelectItem>
                              <SelectItem value="contains">contains</SelectItem>
                              <SelectItem value="missing">missing</SelectItem>
                            </SelectContent>
                          </Select>
                          <ValueTypeSelector
                            valueType={condition.valueType}
                            onValueTypeChange={(type) => {
                              setGroups(groups.map(g => {
                                if (g.id === group.id) {
                                  return {
                                    ...g,
                                    conditions: g.conditions.map(c =>
                                      c.id === condition.id ? { ...c, valueType: type } : c
                                    ),
                                  };
                                }
                                return g;
                              }));
                            }}
                            value={condition.value}
                            onValueChange={(val) => {
                              setGroups(groups.map(g => {
                                if (g.id === group.id) {
                                  return {
                                    ...g,
                                    conditions: g.conditions.map(c =>
                                      c.id === condition.id ? { ...c, value: val } : c
                                    ),
                                  };
                                }
                                return g;
                              }));
                            }}
                            className="flex-1"
                          />
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={condition.auto}
                              onCheckedChange={(checked) => {
                                setGroups(groups.map(g => {
                                  if (g.id === group.id) {
                                    return {
                                      ...g,
                                      conditions: g.conditions.map(c =>
                                        c.id === condition.id ? { ...c, auto: checked } : c
                                      ),
                                    };
                                  }
                                  return g;
                                }));
                              }}
                            />
                            <span className="text-sm">Auto</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDeleteCondition(group.id, condition.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleAddCondition(group.id)}
                    >
                      <Plus className="h-4 w-4 mr-2" />
                      Add Condition
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Card 4: Transparency Preview */}
      <Card className="shadow-sm">
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="text-lg font-semibold">Transparency Preview</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <pre className="bg-muted/50 p-6 rounded-lg text-sm font-mono whitespace-pre-wrap border">
            {generatePreview()}
          </pre>
          <div className="mt-4 p-4 bg-green-50 dark:bg-green-950 border-l-4 border-green-600 text-green-800 dark:text-green-200 text-sm font-semibold rounded-r">
            → ELIGIBLE FOR ADMISSION
          </div>
        </CardContent>
      </Card>

      {/* Save Button */}
      <div className="flex justify-end pt-2">
        <Button onClick={handleSave} size="lg" className="px-8">
          <Save className="h-4 w-4 mr-2" />
          Save Criteria
        </Button>
      </div>
    </div>
  );
}
