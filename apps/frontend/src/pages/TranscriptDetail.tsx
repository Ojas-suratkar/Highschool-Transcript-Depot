// useState not needed in this component
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Badge } from '@/components/ui/badge';

interface Course {
  id: string;
  name: string;
  credits: number;
  grade: string;
  term: string;
  agGroup: string;
  matched: boolean;
}

// Mock data for transcripts
const mockTranscriptDetails: Record<string, any> = {
  '1': {
    studentName: 'John Smith',
    studentId: 'STU-2025-001',
    school: 'Lincoln High School',
    dob: '2006-05-15',
    graduationDate: '2025-06-15',
    address: '123 Main St, Los Angeles, CA 90001',
    gpa: 3.85,
    totalCredits: 30,
    courses: [
      { id: '1', name: 'AP Calculus AB', credits: 5, grade: 'A', term: 'Fall 2024', agGroup: 'C', matched: true },
      { id: '2', name: 'AP Physics', credits: 5, grade: 'B+', term: 'Fall 2024', agGroup: 'D', matched: true },
      { id: '3', name: 'English Literature', credits: 5, grade: 'A-', term: 'Fall 2024', agGroup: 'B', matched: true },
      { id: '4', name: 'Computer Science', credits: 5, grade: 'A', term: 'Spring 2024', agGroup: 'G', matched: true },
      { id: '5', name: 'US History', credits: 5, grade: 'B', term: 'Spring 2024', agGroup: 'A', matched: true },
      { id: '6', name: 'Spanish III', credits: 5, grade: 'A', term: 'Spring 2024', agGroup: 'E', matched: true },
    ],
  },
  '2': {
    studentName: 'Sarah Johnson',
    studentId: 'STU-2025-002',
    school: 'Lincoln High School',
    dob: '2006-08-22',
    graduationDate: '2025-06-15',
    address: '456 Oak Ave, Los Angeles, CA 90002',
    gpa: 3.92,
    totalCredits: 30,
    courses: [
      { id: '1', name: 'AP Calculus AB', credits: 5, grade: 'A', term: 'Fall 2024', agGroup: 'C', matched: true },
      { id: '2', name: 'AP Physics', credits: 5, grade: 'A', term: 'Fall 2024', agGroup: 'D', matched: true },
      { id: '3', name: 'English Literature', credits: 5, grade: 'A', term: 'Fall 2024', agGroup: 'B', matched: true },
      { id: '4', name: 'Computer Science', credits: 5, grade: 'A', term: 'Spring 2024', agGroup: 'G', matched: true },
      { id: '5', name: 'US History', credits: 5, grade: 'A-', term: 'Spring 2024', agGroup: 'A', matched: true },
      { id: '6', name: 'Spanish III', credits: 5, grade: 'A+', term: 'Spring 2024', agGroup: 'E', matched: true },
    ],
  },
  '3': {
    studentName: 'James Wilson',
    studentId: 'STU-2025-003',
    school: 'Lincoln High School',
    dob: '2006-03-10',
    graduationDate: '2025-06-15',
    address: '789 Pine Rd, Los Angeles, CA 90003',
    gpa: 3.45,
    totalCredits: 30,
    courses: [
      { id: '1', name: 'Calculus', credits: 5, grade: 'B+', term: 'Fall 2024', agGroup: 'C', matched: false },
      { id: '2', name: 'Physics', credits: 5, grade: 'C+', term: 'Fall 2024', agGroup: 'D', matched: false },
      { id: '3', name: 'English Literature', credits: 5, grade: 'B', term: 'Fall 2024', agGroup: 'B', matched: true },
      { id: '4', name: 'Computer Science', credits: 5, grade: 'B+', term: 'Spring 2024', agGroup: 'G', matched: true },
      { id: '5', name: 'US History', credits: 5, grade: 'B-', term: 'Spring 2024', agGroup: 'A', matched: true },
      { id: '6', name: 'Spanish III', credits: 5, grade: 'B', term: 'Spring 2024', agGroup: 'E', matched: true },
    ],
  },
};

export default function TranscriptDetail() {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const transcript = mockTranscriptDetails[id || '1'];

  if (!transcript) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-muted-foreground">Transcript not found</p>
        <Button onClick={() => navigate('/transcripts/processed')} className="mt-4">
          Back to Transcripts
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold">Transcript: {transcript.studentName}</h1>
          <p className="text-sm text-muted-foreground">Student ID: {transcript.studentId}</p>
        </div>
      </div>

      <Tabs defaultValue="personal" className="space-y-4">
        <TabsList>
          <TabsTrigger value="personal">Personal Data</TabsTrigger>
          <TabsTrigger value="courses">Courses</TabsTrigger>
          <TabsTrigger value="standardization">Standardization</TabsTrigger>
          <TabsTrigger value="json">Raw JSON</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation Trace</TabsTrigger>
        </TabsList>

        <TabsContent value="personal">
          <Card>
            <CardHeader>
              <CardTitle>Personal Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <p className="text-sm text-muted-foreground">Name</p>
                  <p className="text-lg font-semibold mt-1">{transcript.studentName}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Date of Birth</p>
                  <p className="text-lg font-semibold mt-1">{transcript.dob}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Student ID</p>
                  <p className="text-lg font-semibold mt-1">{transcript.studentId}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">School</p>
                  <p className="text-lg font-semibold mt-1">{transcript.school}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Graduation Date</p>
                  <p className="text-lg font-semibold mt-1">{transcript.graduationDate}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Address</p>
                  <p className="text-lg font-semibold mt-1">{transcript.address}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="courses">
          <Card>
            <CardHeader>
              <CardTitle>Course Records</CardTitle>
              <p className="text-sm text-muted-foreground mt-2">{transcript.courses.length} courses on record</p>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Course</TableHead>
                      <TableHead>Credits</TableHead>
                      <TableHead>Grade</TableHead>
                      <TableHead>Term</TableHead>
                      <TableHead>A-G Group</TableHead>
                      <TableHead>Match Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {transcript.courses.map((course: Course) => (
                      <TableRow key={course.id}>
                        <TableCell className="font-medium">{course.name}</TableCell>
                        <TableCell>{course.credits}</TableCell>
                        <TableCell>{course.grade}</TableCell>
                        <TableCell>{course.term}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{course.agGroup}</Badge>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={course.matched ? 'pass' : 'fail'} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="standardization">
          <Card>
            <CardHeader>
              <CardTitle>Standardization Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Total Credits</p>
                  <p className="text-3xl font-bold">{transcript.totalCredits}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Weighted GPA</p>
                  <p className="text-3xl font-bold text-green-600">{transcript.gpa}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Unweighted GPA</p>
                  <p className="text-3xl font-bold">{(transcript.gpa - 0.15).toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">A-G Requirements</p>
                  <p className="text-3xl font-bold text-green-600">Met</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="json">
          <Card>
            <CardHeader>
              <CardTitle>Raw JSON Data</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="bg-muted p-4 rounded-lg overflow-auto max-h-[600px] text-sm font-mono">
                {JSON.stringify(transcript, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="evaluation">
          <Card>
            <CardHeader>
              <CardTitle>Evaluation Trace</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 p-3 border rounded-lg">
                <StatusBadge status="pass" />
                <span>OCR Processing: Successful</span>
              </div>
              <div className="flex items-center gap-2 p-3 border rounded-lg">
                <StatusBadge status="pass" />
                <span>GPA Extraction: 3.85 identified</span>
              </div>
              <div className="flex items-center gap-2 p-3 border rounded-lg">
                <StatusBadge status="pass" />
                <span>Course Mapping: 6 courses standardized</span>
              </div>
              <div className="flex items-center gap-2 p-3 border rounded-lg">
                <StatusBadge status="pass" />
                <span>UC Match Evaluation: PASS</span>
              </div>
              <div className="flex items-center gap-2 p-3 border rounded-lg">
                <StatusBadge status="pass" />
                <span>A-G Requirements: Met</span>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

