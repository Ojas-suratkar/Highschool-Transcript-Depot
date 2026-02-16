import { useState } from 'react';
import { GraduationCap, Plus, Trash2, Save, Edit, Copy, ChevronDown, ChevronRight, CheckCircle2, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Separator } from '@/components/ui/separator';

interface CourseRequirement {
  id: string;
  type: 'specific' | 'group';
  courseCodes?: string[];
  minCount?: number;
  minGrade?: string;
  logic?: 'AND' | 'OR';
}

interface AdditionalCriteria {
  id: string;
  type: 'gpa' | 'english' | 'standardized' | 'portfolio' | 'experience';
  label: string;
  value: string;
  autoVerifiable: boolean;
}

interface Program {
  id: string;
  name: string;
  degreeLevel: string;
  intakeTerm: string;
  programCode: string;
  courseRequirements: CourseRequirement[];
  additionalCriteria: AdditionalCriteria[];
  version: number;
}

const mockPrograms: Program[] = [
  {
    id: '1',
    name: 'Computer Science',
    degreeLevel: 'Bachelor',
    intakeTerm: 'Fall 2024',
    programCode: 'CS-BS-2024',
    courseRequirements: [
      { id: '1', type: 'specific', courseCodes: ['MATH101'], minGrade: 'B', logic: 'AND' },
      { id: '2', type: 'group', courseCodes: ['PHYS201', 'PHYS202'], minCount: 1, minGrade: 'C', logic: 'OR' },
    ],
    additionalCriteria: [
      { id: '1', type: 'gpa', label: 'Minimum GPA', value: '3.0', autoVerifiable: true },
      { id: '2', type: 'english', label: 'TOEFL Score', value: '80', autoVerifiable: false },
    ],
    version: 1,
  },
];

export default function ProgramRequirements() {
  const { toast } = useToast();
  const [programs, setPrograms] = useState<Program[]>(mockPrograms);
  const [selectedProgram, setSelectedProgram] = useState<Program | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['course-req', 'additional']));

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(section)) {
        newSet.delete(section);
      } else {
        newSet.add(section);
      }
      return newSet;
    });
  };

  const handleAddProgram = () => {
    const newProgram: Program = {
      id: Date.now().toString(),
      name: '',
      degreeLevel: 'Bachelor',
      intakeTerm: '',
      programCode: '',
      courseRequirements: [],
      additionalCriteria: [],
      version: 1,
    };
    setPrograms([...programs, newProgram]);
    setSelectedProgram(newProgram);
    setIsEditing(true);
  };

  const handleSaveProgram = () => {
    if (!selectedProgram) return;
    
    setPrograms(programs.map(p => p.id === selectedProgram.id ? selectedProgram : p));
    setIsEditing(false);
    toast({
      title: 'Program saved',
      description: 'Program requirements have been updated successfully',
    });
  };

  const handleAddCourseRequirement = () => {
    if (!selectedProgram) return;
    
    const newReq: CourseRequirement = {
      id: Date.now().toString(),
      type: 'specific',
      courseCodes: [],
      minGrade: 'C',
      logic: 'AND',
    };
    
    setSelectedProgram({
      ...selectedProgram,
      courseRequirements: [...selectedProgram.courseRequirements, newReq],
    });
  };

  const handleAddAdditionalCriteria = () => {
    if (!selectedProgram) return;
    
    const newCriteria: AdditionalCriteria = {
      id: Date.now().toString(),
      type: 'gpa',
      label: '',
      value: '',
      autoVerifiable: false,
    };
    
    setSelectedProgram({
      ...selectedProgram,
      additionalCriteria: [...selectedProgram.additionalCriteria, newCriteria],
    });
  };

  const handleRemoveCourseRequirement = (id: string) => {
    if (!selectedProgram) return;
    setSelectedProgram({
      ...selectedProgram,
      courseRequirements: selectedProgram.courseRequirements.filter(r => r.id !== id),
    });
  };

  const handleRemoveAdditionalCriteria = (id: string) => {
    if (!selectedProgram) return;
    setSelectedProgram({
      ...selectedProgram,
      additionalCriteria: selectedProgram.additionalCriteria.filter(c => c.id !== id),
    });
  };

  const updateCourseRequirement = (id: string, field: keyof CourseRequirement, value: any) => {
    if (!selectedProgram) return;
    setSelectedProgram({
      ...selectedProgram,
      courseRequirements: selectedProgram.courseRequirements.map(r =>
        r.id === id ? { ...r, [field]: value } : r
      ),
    });
  };

  const updateAdditionalCriteria = (id: string, field: keyof AdditionalCriteria, value: any) => {
    if (!selectedProgram) return;
    setSelectedProgram({
      ...selectedProgram,
      additionalCriteria: selectedProgram.additionalCriteria.map(c =>
        c.id === id ? { ...c, [field]: value } : c
      ),
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Programs & Prerequisites</h1>
          <p className="text-muted-foreground">
            Manage academic programs and define admission requirements with UC Doorway integration
          </p>
        </div>
        <Button onClick={handleAddProgram} className="gap-2 bg-[#3B5BDB] hover:bg-[#2E4AC4]">
          <Plus className="h-4 w-4" />
          Add Program
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        {/* Programs List */}
        <Card className="shadow-card md:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <GraduationCap className="h-5 w-5" />
              Programs
            </CardTitle>
            <CardDescription>{programs.length} programs configured</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {programs.map((program) => (
                <div
                  key={program.id}
                  onClick={() => {
                    setSelectedProgram(program);
                    setIsEditing(false);
                  }}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    selectedProgram?.id === program.id
                      ? 'bg-[#E0E7FF] border-[#C7D2FE]'
                      : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="font-medium">{program.name || 'Untitled Program'}</div>
                  <div className="text-sm text-muted-foreground">{program.programCode}</div>
                  <div className="flex gap-1 mt-2">
                    <Badge variant="outline" className="text-xs">
                      {program.degreeLevel}
                    </Badge>
                    <Badge variant="outline" className="text-xs">
                      v{program.version}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Program Details */}
        <Card className="shadow-card md:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>
                  {selectedProgram ? (selectedProgram.name || 'Untitled Program') : 'Select a Program'}
                </CardTitle>
                <CardDescription>
                  {selectedProgram
                    ? 'Configure program details and admission requirements'
                    : 'Select a program from the list to view and edit'}
                </CardDescription>
              </div>
              {selectedProgram && (
                <div className="flex gap-2">
                  {!isEditing ? (
                    <>
                      <Button variant="outline" size="sm" onClick={() => setIsEditing(true)}>
                        <Edit className="h-4 w-4 mr-2" />
                        Edit
                      </Button>
                      <Button variant="outline" size="sm">
                        <Copy className="h-4 w-4 mr-2" />
                        Duplicate
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="outline" size="sm" onClick={() => setIsEditing(false)}>
                        Cancel
                      </Button>
                      <Button size="sm" onClick={handleSaveProgram} className="bg-[#3B5BDB] hover:bg-[#2E4AC4]">
                        <Save className="h-4 w-4 mr-2" />
                        Save
                      </Button>
                    </>
                  )}
                </div>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {!selectedProgram ? (
              <div className="text-center py-12 text-muted-foreground">
                <GraduationCap className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Select a program to view and edit its requirements</p>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Basic Information */}
                <div className="space-y-4">
                  <h3 className="font-semibold text-lg">Basic Information</h3>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Program Name</Label>
                      <Input
                        value={selectedProgram.name}
                        onChange={(e) =>
                          setSelectedProgram({ ...selectedProgram, name: e.target.value })
                        }
                        disabled={!isEditing}
                        placeholder="e.g., Computer Science"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Program Code</Label>
                      <Input
                        value={selectedProgram.programCode}
                        onChange={(e) =>
                          setSelectedProgram({ ...selectedProgram, programCode: e.target.value })
                        }
                        disabled={!isEditing}
                        placeholder="e.g., CS-BS-2024"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Degree Level</Label>
                      <Select
                        value={selectedProgram.degreeLevel}
                        onValueChange={(value) =>
                          setSelectedProgram({ ...selectedProgram, degreeLevel: value })
                        }
                        disabled={!isEditing}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Bachelor">Bachelor's</SelectItem>
                          <SelectItem value="Master">Master's</SelectItem>
                          <SelectItem value="Doctorate">Doctorate</SelectItem>
                          <SelectItem value="Certificate">Certificate</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Intake Term</Label>
                      <Input
                        value={selectedProgram.intakeTerm}
                        onChange={(e) =>
                          setSelectedProgram({ ...selectedProgram, intakeTerm: e.target.value })
                        }
                        disabled={!isEditing}
                        placeholder="e.g., Fall 2024"
                      />
                    </div>
                  </div>
                </div>

                <Separator />

                {/* Course Requirements */}
                <Collapsible
                  open={expandedSections.has('course-req')}
                  onOpenChange={() => toggleSection('course-req')}
                >
                  <div className="flex items-center justify-between">
                    <CollapsibleTrigger className="flex items-center gap-2 hover:text-primary">
                      {expandedSections.has('course-req') ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                      <h3 className="font-semibold text-lg">Course Requirements</h3>
                    </CollapsibleTrigger>
                    {isEditing && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleAddCourseRequirement}
                        className="gap-2"
                      >
                        <Plus className="h-4 w-4" />
                        Add Requirement
                      </Button>
                    )}
                  </div>
                  <CollapsibleContent className="mt-4 space-y-3">
                    {selectedProgram.courseRequirements.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground border rounded-lg">
                        <p>No course requirements defined</p>
                        {isEditing && (
                          <Button
                            variant="link"
                            onClick={handleAddCourseRequirement}
                            className="mt-2"
                          >
                            Add your first requirement
                          </Button>
                        )}
                      </div>
                    ) : (
                      selectedProgram.courseRequirements.map((req, index) => (
                        <div
                          key={req.id}
                          className="p-4 border rounded-lg bg-slate-50 space-y-3"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-sm">Requirement {index + 1}</span>
                            {isEditing && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRemoveCourseRequirement(req.id)}
                                className="text-red-600 hover:text-red-700"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                          <div className="grid gap-3 md:grid-cols-4">
                            <div className="space-y-2">
                              <Label className="text-xs">Type</Label>
                              <Select
                                value={req.type}
                                onValueChange={(value) =>
                                  updateCourseRequirement(req.id, 'type', value)
                                }
                                disabled={!isEditing}
                              >
                                <SelectTrigger className="h-9">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="specific">Specific Course</SelectItem>
                                  <SelectItem value="group">Course Group</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-2">
                              <Label className="text-xs">Course Code(s)</Label>
                              <Input
                                value={req.courseCodes?.join(', ') || ''}
                                onChange={(e) =>
                                  updateCourseRequirement(
                                    req.id,
                                    'courseCodes',
                                    e.target.value.split(',').map((c) => c.trim())
                                  )
                                }
                                disabled={!isEditing}
                                placeholder="e.g., MATH101, PHYS201"
                                className="h-9"
                              />
                            </div>
                            {req.type === 'group' && (
                              <div className="space-y-2">
                                <Label className="text-xs">Min Count</Label>
                                <Input
                                  type="number"
                                  value={req.minCount || 1}
                                  onChange={(e) =>
                                    updateCourseRequirement(
                                      req.id,
                                      'minCount',
                                      parseInt(e.target.value)
                                    )
                                  }
                                  disabled={!isEditing}
                                  className="h-9"
                                />
                              </div>
                            )}
                            <div className="space-y-2">
                              <Label className="text-xs">Min Grade</Label>
                              <Select
                                value={req.minGrade}
                                onValueChange={(value) =>
                                  updateCourseRequirement(req.id, 'minGrade', value)
                                }
                                disabled={!isEditing}
                              >
                                <SelectTrigger className="h-9">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="A">A</SelectItem>
                                  <SelectItem value="B">B</SelectItem>
                                  <SelectItem value="C">C</SelectItem>
                                  <SelectItem value="D">D</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            {req.type === 'group' && (
                              <div className="space-y-2">
                                <Label className="text-xs">Logic</Label>
                                <Select
                                  value={req.logic}
                                  onValueChange={(value) =>
                                    updateCourseRequirement(req.id, 'logic', value)
                                  }
                                  disabled={!isEditing}
                                >
                                  <SelectTrigger className="h-9">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="AND">AND (All required)</SelectItem>
                                    <SelectItem value="OR">OR (Any one)</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs">
                            <CheckCircle2 className="h-3 w-3 text-green-600" />
                            <span className="text-green-700">Auto-verifiable from UC Doorway</span>
                          </div>
                        </div>
                      ))
                    )}
                  </CollapsibleContent>
                </Collapsible>

                <Separator />

                {/* Additional Criteria */}
                <Collapsible
                  open={expandedSections.has('additional')}
                  onOpenChange={() => toggleSection('additional')}
                >
                  <div className="flex items-center justify-between">
                    <CollapsibleTrigger className="flex items-center gap-2 hover:text-primary">
                      {expandedSections.has('additional') ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                      <h3 className="font-semibold text-lg">Additional Criteria</h3>
                    </CollapsibleTrigger>
                    {isEditing && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleAddAdditionalCriteria}
                        className="gap-2"
                      >
                        <Plus className="h-4 w-4" />
                        Add Criteria
                      </Button>
                    )}
                  </div>
                  <CollapsibleContent className="mt-4 space-y-3">
                    <p className="text-sm text-muted-foreground">
                      Define non-course requirements such as GPA, test scores, portfolios, or work
                      experience
                    </p>
                    {selectedProgram.additionalCriteria.length === 0 ? (
                      <div className="text-center py-8 text-muted-foreground border rounded-lg">
                        <p>No additional criteria defined</p>
                        {isEditing && (
                          <Button
                            variant="link"
                            onClick={handleAddAdditionalCriteria}
                            className="mt-2"
                          >
                            Add your first criteria
                          </Button>
                        )}
                      </div>
                    ) : (
                      selectedProgram.additionalCriteria.map((criteria) => (
                        <div
                          key={criteria.id}
                          className="p-4 border rounded-lg bg-slate-50 space-y-3"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              {criteria.autoVerifiable ? (
                                <CheckCircle2 className="h-4 w-4 text-green-600" />
                              ) : (
                                <AlertCircle className="h-4 w-4 text-orange-600" />
                              )}
                              <span className="font-medium text-sm">
                                {criteria.autoVerifiable
                                  ? 'Auto-verifiable'
                                  : 'Requires manual review'}
                              </span>
                            </div>
                            {isEditing && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRemoveAdditionalCriteria(criteria.id)}
                                className="text-red-600 hover:text-red-700"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                          <div className="grid gap-3 md:grid-cols-3">
                            <div className="space-y-2">
                              <Label className="text-xs">Type</Label>
                              <Select
                                value={criteria.type}
                                onValueChange={(value) =>
                                  updateAdditionalCriteria(criteria.id, 'type', value)
                                }
                                disabled={!isEditing}
                              >
                                <SelectTrigger className="h-9">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="gpa">GPA</SelectItem>
                                  <SelectItem value="english">English Proficiency</SelectItem>
                                  <SelectItem value="standardized">Standardized Test</SelectItem>
                                  <SelectItem value="portfolio">Portfolio</SelectItem>
                                  <SelectItem value="experience">Work Experience</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="space-y-2">
                              <Label className="text-xs">Label</Label>
                              <Input
                                value={criteria.label}
                                onChange={(e) =>
                                  updateAdditionalCriteria(criteria.id, 'label', e.target.value)
                                }
                                disabled={!isEditing}
                                placeholder="e.g., Minimum GPA"
                                className="h-9"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-xs">Required Value</Label>
                              <Input
                                value={criteria.value}
                                onChange={(e) =>
                                  updateAdditionalCriteria(criteria.id, 'value', e.target.value)
                                }
                                disabled={!isEditing}
                                placeholder="e.g., 3.0"
                                className="h-9"
                              />
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </CollapsibleContent>
                </Collapsible>

                {/* Version Info */}
                <div className="pt-4 border-t">
                  <div className="flex items-center justify-between text-sm text-muted-foreground">
                    <span>Version {selectedProgram.version}</span>
                    {isEditing && (
                      <Button variant="link" size="sm" className="text-xs">
                        View Version History
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}



