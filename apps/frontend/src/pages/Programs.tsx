import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
// Removed unused icon imports; keep Plus which is used later
import { Plus, Trash2, Save, ChevronDown, ChevronRight, CheckCircle2, AlertCircle, Info } from 'lucide-react';
import type { Program } from '@/types/admissions';

interface CourseRequirement {
  id: string;
  courseCode: string;
  courseName: string;
  minimumGrade: string;
  isAutoVerifiable: boolean;
}

interface CourseGroup {
  id: string;
  groupName: string;
  courses: string[];
  requiredCount: number;
  minimumGrade: string;
  operator: 'AND' | 'OR';
  isAutoVerifiable: boolean;
}

interface AdditionalCriterion {
  id: string;
  type: 'gpa' | 'english_test' | 'standardized_test' | 'portfolio' | 'work_experience' | 'other';
  name: string;
  description: string;
  threshold?: string;
  isRequired: boolean;
  isAutoVerifiable: boolean;
}

const mockPrograms: Program[] = [
  {
    id: '1',
    name: 'Computer Science',
    code: 'CS-BS',
    degreeLevel: 'undergraduate',
    intakeTerms: ['Fall 2025', 'Spring 2026'],
    status: 'active',
    applicantCount: 145,
    requirements: {
      id: 'req-1',
      programId: '1',
      rules: []
    }
  },
  {
    id: '2',
    name: 'Business Administration',
    code: 'BA-BS',
    degreeLevel: 'undergraduate',
    intakeTerms: ['Fall 2025'],
    status: 'active',
    applicantCount: 98,
    requirements: {
      id: 'req-2',
      programId: '2',
      rules: []
    }
  }
];

export default function Programs() {
  const [programs, setPrograms] = useState<Program[]>(mockPrograms);
  const [selectedProgram, setSelectedProgram] = useState<Program | null>(null);
  const [_isAddingProgram, _setIsAddingProgram] = useState(false);
  const [_isEditingProgram, _setIsEditingProgram] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    courseReqs: true,
    additionalCriteria: true
  });

  // Course Requirements State
  const [courseRequirements, setCourseRequirements] = useState<CourseRequirement[]>([
    {
      id: '1',
      courseCode: 'MATH101',
      courseName: 'Calculus I',
      minimumGrade: 'B',
      isAutoVerifiable: true
    },
    {
      id: '2',
      courseCode: 'PHYS201',
      courseName: 'Physics I',
      minimumGrade: 'C+',
      isAutoVerifiable: true
    }
  ]);

  const [courseGroups, setCourseGroups] = useState<CourseGroup[]>([
    {
      id: '1',
      groupName: 'Mathematics Foundation',
      courses: ['MATH101', 'MATH102', 'MATH201'],
      requiredCount: 2,
      minimumGrade: 'B',
      operator: 'OR',
      isAutoVerifiable: true
    }
  ]);

  // Additional Criteria State
  const [additionalCriteria, setAdditionalCriteria] = useState<AdditionalCriterion[]>([
    {
      id: '1',
      type: 'gpa',
      name: 'Minimum GPA',
      description: 'Overall GPA must be 3.0 or higher',
      threshold: '3.0',
      isRequired: true,
      isAutoVerifiable: true
    },
    {
      id: '2',
      type: 'english_test',
      name: 'TOEFL Score',
      description: 'Minimum TOEFL score of 80',
      threshold: '80',
      isRequired: true,
      isAutoVerifiable: false
    },
    {
      id: '3',
      type: 'portfolio',
      name: 'Portfolio Submission',
      description: 'Submit a portfolio of previous work',
      isRequired: false,
      isAutoVerifiable: false
    }
  ]);

  // Dialog States
  const [showAddCourseDialog, setShowAddCourseDialog] = useState(false);
  const [showAddGroupDialog, setShowAddGroupDialog] = useState(false);
  const [showAddCriterionDialog, setShowAddCriterionDialog] = useState(false);
  const [showProgramDialog, setShowProgramDialog] = useState(false);

  // Form States
  const [newCourse, setNewCourse] = useState<Partial<CourseRequirement>>({});
  const [newGroup, setNewGroup] = useState<Partial<CourseGroup>>({ operator: 'OR' });
  const [newCriterion, setNewCriterion] = useState<Partial<AdditionalCriterion>>({});
  const [programForm, setProgramForm] = useState<Partial<Program>>({});

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const handleAddCourse = () => {
    if (newCourse.courseCode && newCourse.courseName && newCourse.minimumGrade) {
      setCourseRequirements([
        ...courseRequirements,
        {
          id: Date.now().toString(),
          courseCode: newCourse.courseCode,
          courseName: newCourse.courseName,
          minimumGrade: newCourse.minimumGrade,
          isAutoVerifiable: true
        }
      ]);
      setNewCourse({});
      setShowAddCourseDialog(false);
    }
  };

  const handleAddGroup = () => {
    if (newGroup.groupName && newGroup.courses && newGroup.requiredCount && newGroup.minimumGrade) {
      setCourseGroups([
        ...courseGroups,
        {
          id: Date.now().toString(),
          groupName: newGroup.groupName,
          courses: newGroup.courses,
          requiredCount: newGroup.requiredCount,
          minimumGrade: newGroup.minimumGrade,
          operator: newGroup.operator || 'OR',
          isAutoVerifiable: true
        }
      ]);
      setNewGroup({ operator: 'OR' });
      setShowAddGroupDialog(false);
    }
  };

  const handleAddCriterion = () => {
    if (newCriterion.name && newCriterion.description && newCriterion.type) {
      setAdditionalCriteria([
        ...additionalCriteria,
        {
          id: Date.now().toString(),
          type: newCriterion.type,
          name: newCriterion.name,
          description: newCriterion.description,
          threshold: newCriterion.threshold,
          isRequired: newCriterion.isRequired || false,
          isAutoVerifiable: newCriterion.isAutoVerifiable || false
        }
      ]);
      setNewCriterion({});
      setShowAddCriterionDialog(false);
    }
  };

  const handleDeleteCourse = (id: string) => {
    setCourseRequirements(courseRequirements.filter(c => c.id !== id));
  };

  const handleDeleteGroup = (id: string) => {
    setCourseGroups(courseGroups.filter(g => g.id !== id));
  };

  const handleDeleteCriterion = (id: string) => {
    setAdditionalCriteria(additionalCriteria.filter(c => c.id !== id));
  };

  const handleAddProgram = () => {
    if (programForm.name && programForm.code && programForm.degreeLevel) {
      const newProgram: Program = {
        id: Date.now().toString(),
        name: programForm.name,
        code: programForm.code,
        degreeLevel: programForm.degreeLevel,
        intakeTerms: programForm.intakeTerms || [],
        status: 'active',
        applicantCount: 0,
        requirements: {
          id: `req-${Date.now()}`,
          programId: Date.now().toString(),
          rules: []
        }
      };
      setPrograms([...programs, newProgram]);
      setProgramForm({});
      setShowProgramDialog(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Programs & Prerequisites</h1>
          <p className="text-muted-foreground">Manage academic programs and define admission requirements</p>
        </div>
        <Button onClick={() => setShowProgramDialog(true)} className="bg-blue-600 hover:bg-blue-700">
          <Plus className="h-4 w-4 mr-2" />
          Add Program
        </Button>
      </div>

      {/* Programs List */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {programs.map((program) => (
          <Card
            key={program.id}
            className={`shadow-card cursor-pointer transition-all hover:shadow-lg ${
              selectedProgram?.id === program.id ? 'ring-2 ring-blue-500' : ''
            }`}
            onClick={() => setSelectedProgram(program)}
          >
            <CardHeader>
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <CardTitle className="text-lg">{program.name}</CardTitle>
                  <CardDescription className="mt-1">{program.code}</CardDescription>
                </div>
                <Badge
                  variant={program.status === 'active' ? 'default' : 'secondary'}
                  className={program.status === 'active' ? 'bg-green-500' : ''}
                >
                  {program.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Degree Level:</span>
                  <span className="font-medium capitalize">{program.degreeLevel}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Applicants:</span>
                  <span className="font-medium">{program.applicantCount}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Intake Terms:</span>
                  <span className="font-medium">{program.intakeTerms.length}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Prerequisites Builder */}
      {selectedProgram && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold">Prerequisites for {selectedProgram.name}</h2>
              <p className="text-sm text-muted-foreground">Define course requirements and additional criteria</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm">
                <Save className="h-4 w-4 mr-2" />
                Save Changes
              </Button>
              <Button variant="outline" size="sm">
                Version History
              </Button>
            </div>
          </div>

          {/* Course-Based Requirements */}
          <Card className="shadow-card">
            <CardHeader>
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => toggleSection('courseReqs')}
              >
                <div className="flex items-center gap-2">
                  {expandedSections.courseReqs ? (
                    <ChevronDown className="h-5 w-5" />
                  ) : (
                    <ChevronRight className="h-5 w-5" />
                  )}
                  <CardTitle>Course-Based Requirements</CardTitle>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowAddCourseDialog(true);
                    }}
                  >
                    <Plus className="h-4 w-4 mr-2" />
                    Add Course
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowAddGroupDialog(true);
                    }}
                  >
                    <Plus className="h-4 w-4 mr-2" />
                    Add Group
                  </Button>
                </div>
              </div>
              <CardDescription>
                Define specific courses or course groups required for admission
              </CardDescription>
            </CardHeader>

            {expandedSections.courseReqs && (
              <CardContent className="space-y-4">
                {/* Individual Course Requirements */}
                <div className="space-y-3">
                  <h4 className="text-sm font-medium text-muted-foreground">Required Courses</h4>
                  {courseRequirements.map((course) => (
                    <div
                      key={course.id}
                      className="flex items-center justify-between p-4 border rounded-lg bg-slate-50 hover:bg-slate-100 transition-colors"
                    >
                      <div className="flex items-center gap-4 flex-1">
                        <CheckCircle2 className="h-5 w-5 text-green-600" />
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{course.courseCode}</span>
                            <span className="text-muted-foreground">-</span>
                            <span className="text-sm">{course.courseName}</span>
                          </div>
                          <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
                            <span>Minimum Grade: <span className="font-medium text-foreground">{course.minimumGrade}</span></span>
                            {course.isAutoVerifiable && (
                              <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                                <CheckCircle2 className="h-3 w-3 mr-1" />
                                Auto-verifiable
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDeleteCourse(course.id)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>

                {/* Course Groups */}
                {courseGroups.length > 0 && (
                  <div className="space-y-3 mt-6">
                    <h4 className="text-sm font-medium text-muted-foreground">Course Groups (AND/OR Logic)</h4>
                    {courseGroups.map((group) => (
                      <div
                        key={group.id}
                        className="p-4 border rounded-lg bg-amber-50 hover:bg-amber-100 transition-colors"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-2">
                              <AlertCircle className="h-5 w-5 text-amber-600" />
                              <span className="font-medium">{group.groupName}</span>
                              <Badge className="bg-amber-600">{group.operator}</Badge>
                            </div>
                            <div className="ml-7 space-y-2">
                              <p className="text-sm text-muted-foreground">
                                Complete <span className="font-medium text-foreground">{group.requiredCount}</span> of the following courses with minimum grade <span className="font-medium text-foreground">{group.minimumGrade}</span>:
                              </p>
                              <div className="flex flex-wrap gap-2">
                                {group.courses.map((course, idx) => (
                                  <Badge key={idx} variant="outline" className="bg-white">
                                    {course}
                                  </Badge>
                                ))}
                              </div>
                              {group.isAutoVerifiable && (
                                <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">
                                  <CheckCircle2 className="h-3 w-3 mr-1" />
                                  Auto-verifiable from UC Doorway
                                </Badge>
                              )}
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDeleteGroup(group.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            )}
          </Card>

          {/* Additional Criteria */}
          <Card className="shadow-card">
            <CardHeader>
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => toggleSection('additionalCriteria')}
              >
                <div className="flex items-center gap-2">
                  {expandedSections.additionalCriteria ? (
                    <ChevronDown className="h-5 w-5" />
                  ) : (
                    <ChevronRight className="h-5 w-5" />
                  )}
                  <CardTitle>Additional Criteria</CardTitle>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowAddCriterionDialog(true);
                  }}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Criterion
                </Button>
              </div>
              <CardDescription>
                Non-course requirements such as GPA, test scores, portfolios, or work experience
              </CardDescription>
            </CardHeader>

            {expandedSections.additionalCriteria && (
              <CardContent className="space-y-3">
                {additionalCriteria.map((criterion) => (
                  <div
                    key={criterion.id}
                    className="flex items-start justify-between p-4 border rounded-lg bg-purple-50 hover:bg-purple-100 transition-colors"
                  >
                    <div className="flex items-start gap-4 flex-1">
                      <Info className="h-5 w-5 text-purple-600 mt-0.5" />
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium">{criterion.name}</span>
                          {criterion.isRequired && (
                            <Badge className="bg-red-500">Required</Badge>
                          )}
                          {!criterion.isRequired && (
                            <Badge variant="outline">Optional</Badge>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground mb-2">
                          {criterion.description}
                        </p>
                        {criterion.threshold && (
                          <p className="text-sm">
                            <span className="text-muted-foreground">Threshold:</span>{' '}
                            <span className="font-medium">{criterion.threshold}</span>
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-2">
                          <Badge
                            variant="outline"
                            className={
                              criterion.isAutoVerifiable
                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                : 'bg-orange-50 text-orange-700 border-orange-200'
                            }
                          >
                            {criterion.isAutoVerifiable ? (
                              <>
                                <CheckCircle2 className="h-3 w-3 mr-1" />
                                Auto-verifiable from UC Doorway
                              </>
                            ) : (
                              <>
                                <AlertCircle className="h-3 w-3 mr-1" />
                                Requires manual review
                              </>
                            )}
                          </Badge>
                          <Badge variant="outline" className="capitalize">
                            {criterion.type.replace('_', ' ')}
                          </Badge>
                        </div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDeleteCriterion(criterion.id)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                ))}
              </CardContent>
            )}
          </Card>
        </div>
      )}

      {/* Add Course Dialog */}
      <Dialog open={showAddCourseDialog} onOpenChange={setShowAddCourseDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Course Requirement</DialogTitle>
            <DialogDescription>
              Add a specific course that applicants must complete
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="courseCode">Course Code</Label>
              <Input
                id="courseCode"
                placeholder="e.g., MATH101"
                value={newCourse.courseCode || ''}
                onChange={(e) => setNewCourse({ ...newCourse, courseCode: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="courseName">Course Name</Label>
              <Input
                id="courseName"
                placeholder="e.g., Calculus I"
                value={newCourse.courseName || ''}
                onChange={(e) => setNewCourse({ ...newCourse, courseName: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="minimumGrade">Minimum Grade</Label>
              <Select
                value={newCourse.minimumGrade || ''}
                onValueChange={(value) => setNewCourse({ ...newCourse, minimumGrade: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select minimum grade" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="A">A</SelectItem>
                  <SelectItem value="A-">A-</SelectItem>
                  <SelectItem value="B+">B+</SelectItem>
                  <SelectItem value="B">B</SelectItem>
                  <SelectItem value="B-">B-</SelectItem>
                  <SelectItem value="C+">C+</SelectItem>
                  <SelectItem value="C">C</SelectItem>
                  <SelectItem value="C-">C-</SelectItem>
                  <SelectItem value="D">D</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddCourseDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddCourse} className="bg-blue-600 hover:bg-blue-700">
              Add Course
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Course Group Dialog */}
      <Dialog open={showAddGroupDialog} onOpenChange={setShowAddGroupDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Course Group</DialogTitle>
            <DialogDescription>
              Create a group of courses where applicants must complete a minimum number
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="groupName">Group Name</Label>
              <Input
                id="groupName"
                placeholder="e.g., Mathematics Foundation"
                value={newGroup.groupName || ''}
                onChange={(e) => setNewGroup({ ...newGroup, groupName: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="courses">Course Codes (comma-separated)</Label>
              <Input
                id="courses"
                placeholder="e.g., MATH101, MATH102, MATH201"
                value={newGroup.courses?.join(', ') || ''}
                onChange={(e) => setNewGroup({
                  ...newGroup,
                  courses: e.target.value.split(',').map(c => c.trim()).filter(Boolean)
                })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="requiredCount">Required Count</Label>
                <Input
                  id="requiredCount"
                  type="number"
                  min="1"
                  placeholder="e.g., 2"
                  value={newGroup.requiredCount || ''}
                  onChange={(e) => setNewGroup({ ...newGroup, requiredCount: parseInt(e.target.value) })}
                />
              </div>
              <div>
                <Label htmlFor="groupMinGrade">Minimum Grade</Label>
                <Select
                  value={newGroup.minimumGrade || ''}
                  onValueChange={(value) => setNewGroup({ ...newGroup, minimumGrade: value })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select grade" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="A">A</SelectItem>
                    <SelectItem value="B">B</SelectItem>
                    <SelectItem value="C">C</SelectItem>
                    <SelectItem value="D">D</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="operator">Logic Operator</Label>
              <Select
                value={newGroup.operator || 'OR'}
                onValueChange={(value: 'AND' | 'OR') => setNewGroup({ ...newGroup, operator: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="OR">OR (any of the courses)</SelectItem>
                  <SelectItem value="AND">AND (all courses required)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddGroupDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddGroup} className="bg-blue-600 hover:bg-blue-700">
              Add Group
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Additional Criterion Dialog */}
      <Dialog open={showAddCriterionDialog} onOpenChange={setShowAddCriterionDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Additional Criterion</DialogTitle>
            <DialogDescription>
              Add a non-course requirement for admission
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="criterionType">Criterion Type</Label>
              <Select
                value={newCriterion.type || ''}
                onValueChange={(value: any) => setNewCriterion({ ...newCriterion, type: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gpa">GPA Requirement</SelectItem>
                  <SelectItem value="english_test">English Proficiency Test</SelectItem>
                  <SelectItem value="standardized_test">Standardized Test (SAT/ACT)</SelectItem>
                  <SelectItem value="portfolio">Portfolio</SelectItem>
                  <SelectItem value="work_experience">Work Experience</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="criterionName">Name</Label>
              <Input
                id="criterionName"
                placeholder="e.g., Minimum GPA"
                value={newCriterion.name || ''}
                onChange={(e) => setNewCriterion({ ...newCriterion, name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="criterionDescription">Description</Label>
              <Textarea
                id="criterionDescription"
                placeholder="Describe the requirement..."
                value={newCriterion.description || ''}
                onChange={(e) => setNewCriterion({ ...newCriterion, description: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="threshold">Threshold (optional)</Label>
              <Input
                id="threshold"
                placeholder="e.g., 3.0, 80, etc."
                value={newCriterion.threshold || ''}
                onChange={(e) => setNewCriterion({ ...newCriterion, threshold: e.target.value })}
              />
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="isRequired"
                checked={newCriterion.isRequired || false}
                onChange={(e) => setNewCriterion({ ...newCriterion, isRequired: e.target.checked })}
                className="rounded border-gray-300"
              />
              <Label htmlFor="isRequired" className="font-normal">
                This criterion is required
              </Label>
            </div>
            <div className="flex items-center space-x-2">
              <input
                type="checkbox"
                id="isAutoVerifiable"
                checked={newCriterion.isAutoVerifiable || false}
                onChange={(e) => setNewCriterion({ ...newCriterion, isAutoVerifiable: e.target.checked })}
                className="rounded border-gray-300"
              />
              <Label htmlFor="isAutoVerifiable" className="font-normal">
                Auto-verifiable from UC Doorway
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddCriterionDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddCriterion} className="bg-blue-600 hover:bg-blue-700">
              Add Criterion
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Program Dialog */}
      <Dialog open={showProgramDialog} onOpenChange={setShowProgramDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Program</DialogTitle>
            <DialogDescription>
              Create a new academic program
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="programName">Program Name</Label>
              <Input
                id="programName"
                placeholder="e.g., Computer Science"
                value={programForm.name || ''}
                onChange={(e) => setProgramForm({ ...programForm, name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="programCode">Program Code</Label>
              <Input
                id="programCode"
                placeholder="e.g., CS-BS"
                value={programForm.code || ''}
                onChange={(e) => setProgramForm({ ...programForm, code: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="degreeLevel">Degree Level</Label>
              <Select
                value={programForm.degreeLevel || ''}
                onValueChange={(value: any) => setProgramForm({ ...programForm, degreeLevel: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select degree level" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="undergraduate">Undergraduate</SelectItem>
                  <SelectItem value="graduate">Graduate</SelectItem>
                  <SelectItem value="doctoral">Doctoral</SelectItem>
                  <SelectItem value="certificate">Certificate</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="intakeTerms">Intake Terms (comma-separated)</Label>
              <Input
                id="intakeTerms"
                placeholder="e.g., Fall 2025, Spring 2026"
                value={programForm.intakeTerms?.join(', ') || ''}
                onChange={(e) => setProgramForm({
                  ...programForm,
                  intakeTerms: e.target.value.split(',').map(t => t.trim()).filter(Boolean)
                })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowProgramDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddProgram} className="bg-blue-600 hover:bg-blue-700">
              Create Program
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

