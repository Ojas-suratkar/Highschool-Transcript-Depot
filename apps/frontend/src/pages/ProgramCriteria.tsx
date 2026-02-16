import { useState, useEffect } from 'react';
import { Plus, GripVertical, Trash2, GraduationCap } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
// Note: Switch and Select components were unused in this file and removed to satisfy the linter
import { TermSelector } from '@/components/shared/TermSelector';
import { ValueTypeSelector, ValueType } from '@/components/shared/ValueTypeSelector';
import { getAcademicTerms } from '@/lib/admissionsApi';
import type { AcademicTerm } from '@/types/admissions';

interface Prerequisite {
  id: string;
  courseName: string;
  valueType: ValueType;
  minValue: string;
}

interface Requirement {
  id: string;
  type: 'course' | 'group' | 'grade' | 'marks' | 'gpa';
  description: string;
  minValue: string;
  valueType: ValueType;
  termId: string;
  required: boolean;
  autoVerifiable: boolean;
}

interface ProgramCriteria {
  id: string;
  name: string;
  termId: string;
  version: number;
  prerequisites: Prerequisite[];
  requirements: Requirement[];
  additionalCriteria: Requirement[];
}

export default function ProgramCriteria() {
  const [programs, setPrograms] = useState<ProgramCriteria[]>([]);
  const [terms, setTerms] = useState<AcademicTerm[]>([]);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newProgramName, setNewProgramName] = useState('');
  const [newProgramTerm, setNewProgramTerm] = useState('');

  useEffect(() => {
    getAcademicTerms().then(setTerms);
    
    // Load from localStorage
    const currentTerm = terms.find(t => t.isCurrent);
    if (currentTerm) {
      const stored = localStorage.getItem(`programCriteria-${currentTerm.id}`);
      if (stored) {
        setPrograms(JSON.parse(stored));
      } else {
        // Mock data
        setPrograms([
          {
            id: '1',
            name: 'Computer Science (MS)',
            termId: currentTerm.id,
            version: 3,
            prerequisites: [
              { id: 'p1', courseName: 'Data Structures', valueType: 'grade', minValue: 'B' },
              { id: 'p2', courseName: 'Algorithms', valueType: 'grade', minValue: 'B' },
            ],
            requirements: [
              {
                id: 'r1',
                type: 'course',
                description: 'Linear Algebra',
                minValue: 'B',
                valueType: 'grade',
                termId: currentTerm.id,
                required: true,
                autoVerifiable: true,
              },
            ],
            additionalCriteria: [],
          },
        ]);
      }
    }
  }, [terms]);

  const savePrograms = (updatedPrograms: ProgramCriteria[]) => {
    setPrograms(updatedPrograms);
    const currentTerm = terms.find(t => t.isCurrent);
    if (currentTerm) {
      localStorage.setItem(`programCriteria-${currentTerm.id}`, JSON.stringify(updatedPrograms));
    }
  };

  const addProgram = () => {
    if (!newProgramName || !newProgramTerm) return;
    
    const newProgram: ProgramCriteria = {
      id: Date.now().toString(),
      name: newProgramName,
      termId: newProgramTerm,
      version: 1,
      prerequisites: [],
      requirements: [],
      additionalCriteria: [],
    };
    
    savePrograms([...programs, newProgram]);
    setShowAddDialog(false);
    setNewProgramName('');
    setNewProgramTerm('');
  };

  const deleteProgram = (id: string) => {
    savePrograms(programs.filter(p => p.id !== id));
  };

  const addPrerequisite = (programId: string) => {
    const updated = programs.map(p => {
      if (p.id === programId) {
        return {
          ...p,
          prerequisites: [
            ...p.prerequisites,
            {
              id: Date.now().toString(),
              courseName: '',
              valueType: 'grade' as ValueType,
              minValue: '',
            },
          ],
        };
      }
      return p;
    });
    savePrograms(updated);
  };

  const updatePrerequisite = (programId: string, prereqId: string, updates: Partial<Prerequisite>) => {
    const updated = programs.map(p => {
      if (p.id === programId) {
        return {
          ...p,
          prerequisites: p.prerequisites.map(pr =>
            pr.id === prereqId ? { ...pr, ...updates } : pr
          ),
        };
      }
      return p;
    });
    savePrograms(updated);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Program"
        subtitle="Configure program-specific admission requirements"
        actionLabel="Add Program"
        onAction={() => setShowAddDialog(true)}
      />

      <Accordion type="multiple" className="space-y-4">
        {programs.map((program) => (
          <AccordionItem key={program.id} value={program.id} className="border rounded-lg px-4">
            <AccordionTrigger className="hover:no-underline">
              <div className="flex items-center gap-3 flex-1">
                <GraduationCap className="h-5 w-5 text-primary" />
                <span className="font-semibold">{program.name}</span>
                <Badge variant="outline">{program.prerequisites.length} Prerequisites</Badge>
                <Badge variant="secondary">v{program.version}</Badge>
                <Badge>{terms.find(t => t.id === program.termId)?.name}</Badge>
              </div>
            </AccordionTrigger>
            <AccordionContent className="space-y-6 pt-4">
              {/* Term Selection */}
              <div className="bg-muted p-4 rounded-md">
                <TermSelector
                  value={program.termId}
                  onValueChange={(termId) => {
                    const updated = programs.map(p =>
                      p.id === program.id ? { ...p, termId } : p
                    );
                    savePrograms(updated);
                  }}
                  label="Program Term"
                  showAddButton={false}
                />
              </div>

              {/* Prerequisites */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <Label className="text-base">Prerequisite Courses</Label>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => addPrerequisite(program.id)}
                  >
                    <Plus className="h-4 w-4 mr-1" />
                    Add Course
                  </Button>
                </div>
                <div className="space-y-2">
                  {program.prerequisites.map((prereq) => (
                    <div key={prereq.id} className="flex items-center gap-2 p-3 border rounded-lg">
                      <GripVertical className="h-4 w-4 text-muted-foreground cursor-move" />
                      <Input
                        placeholder="Course name"
                        value={prereq.courseName}
                        onChange={(e) =>
                          updatePrerequisite(program.id, prereq.id, {
                            courseName: e.target.value,
                          })
                        }
                        className="flex-1"
                      />
                      <span className="text-sm text-muted-foreground">Min:</span>
                      <ValueTypeSelector
                        valueType={prereq.valueType}
                        onValueTypeChange={(valueType) =>
                          updatePrerequisite(program.id, prereq.id, { valueType })
                        }
                        value={prereq.minValue}
                        onValueChange={(minValue) =>
                          updatePrerequisite(program.id, prereq.id, { minValue })
                        }
                        className="w-[200px]"
                      />
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          const updated = programs.map(p => {
                            if (p.id === program.id) {
                              return {
                                ...p,
                                prerequisites: p.prerequisites.filter(pr => pr.id !== prereq.id),
                              };
                            }
                            return p;
                          });
                          savePrograms(updated);
                        }}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-between pt-4 border-t">
                <span className="text-sm text-muted-foreground">Version {program.version}</span>
                <div className="flex gap-2">
                  <Button variant="outline">Save New Version</Button>
                  <Button
                    variant="destructive"
                    onClick={() => deleteProgram(program.id)}
                  >
                    Delete Program
                  </Button>
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>

      {/* Add Program Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Program</DialogTitle>
            <DialogDescription>
              Create a new program with admission criteria
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="programName">Program Name</Label>
              <Input
                id="programName"
                placeholder="e.g., Computer Science (MS)"
                value={newProgramName}
                onChange={(e) => setNewProgramName(e.target.value)}
              />
            </div>
            <TermSelector
              value={newProgramTerm}
              onValueChange={setNewProgramTerm}
              label="Term"
              showAddButton={false}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)}>
              Cancel
            </Button>
            <Button onClick={addProgram} disabled={!newProgramName}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}


