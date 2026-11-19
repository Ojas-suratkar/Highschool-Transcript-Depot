import { useEffect, useState } from 'react';
import { GraduationCap, GripVertical, Loader2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

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
import { TermSelector } from '@/components/shared/TermSelector';
import { ValueTypeSelector, ValueType } from '@/components/shared/ValueTypeSelector';
import { useTerm } from '@/contexts/TermContext';
import {
  createProgram,
  createProgramVersion,
  deleteProgram,
  listProgramPrereqs,
  listPrograms,
  updateProgram,
} from '@/lib/api/programs';
interface Prerequisite {
  id: string;
  courseName: string;
  valueType: ValueType;
  minValue: string;
}

interface ProgramCriteriaRecord {
  id: string;
  name: string;
  termId: string;
  yearIntake: string;
  version: number;
  prerequisites: Prerequisite[];
}

function inferValueType(value?: string): ValueType {
  if (!value) return 'grade';
  const numeric = Number(value);
  return Number.isFinite(numeric) && value.trim() !== '' ? 'gpa' : 'grade';
}

export default function ProgramCriteria() {
  const { terms, currentTerm, isLoading: loadingTerms } = useTerm();
  const [programs, setPrograms] = useState<ProgramCriteriaRecord[]>([]);
  const [loadingPrograms, setLoadingPrograms] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newProgramName, setNewProgramName] = useState('');
  const [newProgramTerm, setNewProgramTerm] = useState('');
  const [savingProgramId, setSavingProgramId] = useState<string | null>(null);
  const [deletingProgramId, setDeletingProgramId] = useState<string | null>(null);
  const [creatingProgram, setCreatingProgram] = useState(false);
  const [versioningProgramId, setVersioningProgramId] = useState<string | null>(null);

  const findTermById = (termId: string) => terms.find((term) => term.id === termId);
  const findTermByName = (termName: string) => terms.find((term) => term.term_name === termName);

  const loadPrograms = async () => {
    setLoadingPrograms(true);
    try {
      const summaries = await listPrograms();
      const hydrated = await Promise.all(
        summaries.map(async (program) => {
          const prereqs = await listProgramPrereqs(program.id);
          const matchingTerm = findTermByName(program.year_intake);

          return {
            id: String(program.id),
            name: program.program_name,
            termId: matchingTerm?.id ?? '',
            yearIntake: program.year_intake,
            version: 1,
            prerequisites: prereqs.map((prereq, index) => ({
              id: `${program.id}-${index}`,
              courseName: prereq.course_name,
              valueType: inferValueType(prereq.min_gpa),
              minValue: prereq.min_gpa ?? '',
            })),
          } satisfies ProgramCriteriaRecord;
        })
      );
      setPrograms(hydrated);
    } catch (error: any) {
      toast.error(error?.message || 'Failed to load programs');
    } finally {
      setLoadingPrograms(false);
    }
  };

  useEffect(() => {
    if (!loadingTerms) {
      void loadPrograms();
    }
  }, [loadingTerms, terms]);

  useEffect(() => {
    if (showAddDialog && !newProgramTerm && currentTerm) {
      setNewProgramTerm(currentTerm);
    }
  }, [showAddDialog, currentTerm, newProgramTerm]);

  const updateLocalProgram = (programId: string, updater: (program: ProgramCriteriaRecord) => ProgramCriteriaRecord) => {
    setPrograms((current) =>
      current.map((program) => (program.id === programId ? updater(program) : program))
    );
  };

  const refreshProgram = async (programId: string) => {
    try {
      const summaries = await listPrograms();
      const match = summaries.find((p) => String(p.id) === String(programId));
      if (!match) return;
      const prereqs = await listProgramPrereqs(match.id);
      const matchingTerm = findTermByName(match.year_intake);
      updateLocalProgram(String(match.id), () => ({
        id: String(match.id),
        name: match.program_name,
        termId: matchingTerm?.id ?? '',
        yearIntake: match.year_intake,
        version: 1,
        prerequisites: prereqs.map((prereq, index) => ({
          id: `${match.id}-${index}`,
          courseName: prereq.course_name,
          valueType: inferValueType(prereq.min_gpa),
          minValue: prereq.min_gpa ?? '',
        })),
      }));
    } catch (err) {
      // silent refresh failure
    }
  };

  const addProgram = async () => {
    const trimmedName = newProgramName.trim();
    const termName = findTermById(newProgramTerm)?.term_name;

    if (!trimmedName || !termName) {
      toast.error('Program name and term are required');
      return;
    }

    setCreatingProgram(true);
    try {
      const result = await createProgram({
        program_name: trimmedName,
        year_intake: termName,
        prerequisites: [],
      });
      await loadPrograms(); // keep dialog open; user may add another
      setNewProgramName('');
      setNewProgramTerm(currentTerm || '');
      toast.success(result.created ? 'Program created' : 'Program already exists');
    } catch (error: any) {
      toast.error(error?.message || 'Failed to create program');
    } finally {
      setCreatingProgram(false);
    }
  };

  const saveProgram = async (program: ProgramCriteriaRecord) => {
    const trimmedName = program.name.trim();
    const termName = findTermById(program.termId)?.term_name || program.yearIntake;

    if (!trimmedName || !termName) {
      toast.error('Program name and term are required');
      return;
    }

    setSavingProgramId(program.id);
    try {
      await updateProgram(Number(program.id), {
        program_name: trimmedName,
        year_intake: termName,
        prerequisites: program.prerequisites
          .filter((prereq) => prereq.courseName.trim())
          .map((prereq) => ({
            course_name: prereq.courseName.trim(),
            min_gpa: prereq.minValue.trim() || undefined,
          })),
      });
      await refreshProgram(program.id);
      toast.success('Program saved');
    } catch (error: any) {
      toast.error(error?.message || 'Failed to save program');
    } finally {
      setSavingProgramId(null);
    }
  };

  const saveVersion = async (programId: string) => {
    setVersioningProgramId(programId);
    try {
      await createProgramVersion(Number(programId), 'Saved from Program Criteria UI');
      toast.success('Program version created');
    } catch (error: any) {
      toast.error(error?.message || 'Failed to create program version');
    } finally {
      setVersioningProgramId(null);
    }
  };

  const removeProgram = async (programId: string) => {
    setDeletingProgramId(programId);
    try {
      await deleteProgram(Number(programId));
      setPrograms((current) => current.filter((program) => program.id !== programId));
      toast.success('Program deleted');
    } catch (error: any) {
      toast.error(error?.message || 'Failed to delete program');
    } finally {
      setDeletingProgramId(null);
    }
  };

  const addPrerequisite = (programId: string) => {
    updateLocalProgram(programId, (program) => ({
      ...program,
      prerequisites: [
        ...program.prerequisites,
        {
          id: `${programId}-${Date.now()}`,
          courseName: '',
          valueType: 'grade',
          minValue: '',
        },
      ],
    }));
  };

  const updatePrerequisite = (
    programId: string,
    prereqId: string,
    updates: Partial<Prerequisite>
  ) => {
    updateLocalProgram(programId, (program) => ({
      ...program,
      prerequisites: program.prerequisites.map((prereq) =>
        prereq.id === prereqId ? { ...prereq, ...updates } : prereq
      ),
    }));
  };

  const removePrerequisite = (programId: string, prereqId: string) => {
    updateLocalProgram(programId, (program) => ({
      ...program,
      prerequisites: program.prerequisites.filter((prereq) => prereq.id !== prereqId),
    }));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Program Admission Rules"
        subtitle="Manage programs and their prerequisite course requirements"
        actionLabel="Add Program"
        onAction={() => setShowAddDialog(true)}
      />

      {/* ── Programs ── */}
      <div className="space-y-2">
        <h2 className="text-sm font-semibold">Programs</h2>

      {loadingPrograms ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading programs...
        </div>
      ) : programs.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-sm text-muted-foreground">
          No persisted programs found for the current institution.
        </div>
      ) : (
        <Accordion type="multiple" className="space-y-4">
          {programs.map((program) => {
            const displayedTerm = findTermById(program.termId)?.term_name || program.yearIntake;

            return (
              <AccordionItem key={program.id} value={program.id} className="rounded-lg border px-4">
                <AccordionTrigger className="hover:no-underline">
                  <div className="flex flex-1 items-center gap-3">
                    <GraduationCap className="h-5 w-5 text-primary" />
                    <span className="font-semibold">{program.name}</span>
                    <Badge variant="outline">{program.prerequisites.length} Prerequisites</Badge>
                    <Badge variant="secondary">v{program.version}</Badge>
                    <Badge>{displayedTerm}</Badge>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="space-y-6 pt-4">
                  <div className="rounded-md bg-muted p-4">
                    <div className="space-y-2">
                      <Label>Program Name</Label>
                      <Input
                        value={program.name}
                        onChange={(event) =>
                          updateLocalProgram(program.id, (current) => ({
                            ...current,
                            name: event.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="mt-4">
                      <TermSelector
                        value={program.termId}
                        onValueChange={(termId) =>
                          updateLocalProgram(program.id, (current) => ({
                            ...current,
                            termId,
                            yearIntake: findTermById(termId)?.term_name || current.yearIntake,
                          }))
                        }
                        label="Program Term"
                        showAddButton={false}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="mb-3 flex items-center justify-between">
                      <Label className="text-base">Prerequisite Courses</Label>
                      <Button size="sm" variant="outline" onClick={() => addPrerequisite(program.id)}>
                        <Plus className="mr-1 h-4 w-4" />
                        Add Course
                      </Button>
                    </div>
                    <div className="space-y-2">
                      {program.prerequisites.map((prereq) => (
                        <div key={prereq.id} className="flex items-center gap-2 rounded-lg border p-3">
                          <GripVertical className="h-4 w-4 cursor-move text-muted-foreground" />
                          <Input
                            placeholder="Course name"
                            value={prereq.courseName}
                            onChange={(event) =>
                              updatePrerequisite(program.id, prereq.id, {
                                courseName: event.target.value,
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
                            onClick={() => removePrerequisite(program.id, prereq.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t pt-4">
                    <span className="text-sm text-muted-foreground">Database-backed program</span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        onClick={() => saveVersion(program.id)}
                        disabled={versioningProgramId === program.id}
                      >
                        {versioningProgramId === program.id ? 'Saving Version...' : 'Save New Version'}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => saveProgram(program)}
                        disabled={savingProgramId === program.id}
                      >
                        {savingProgramId === program.id ? 'Saving...' : 'Save Program'}
                      </Button>
                      <Button
                        variant="destructive"
                        onClick={() => removeProgram(program.id)}
                        disabled={deletingProgramId === program.id}
                      >
                        {deletingProgramId === program.id ? 'Deleting...' : 'Delete Program'}
                      </Button>
                    </div>
                  </div>
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      )}
      </div>

      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Program</DialogTitle>
            <DialogDescription>Create a new program with admission criteria</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="programName">Program Name</Label>
              <Input
                id="programName"
                placeholder="e.g., Computer Science (MS)"
                value={newProgramName}
                onChange={(event) => setNewProgramName(event.target.value)}
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
            <Button onClick={addProgram} disabled={creatingProgram || !newProgramName.trim()}>
              {creatingProgram ? 'Creating...' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
