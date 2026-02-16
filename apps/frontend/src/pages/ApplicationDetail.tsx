import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { getApplication } from '@/lib/admissionsApi';
import type { Application } from '@/types/admissions';

export default function ApplicationDetail() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const [application, setApplication] = useState<Application | null>(null);

  useEffect(() => {
    if (applicationId) {
      getApplication(applicationId).then(setApplication);
    }
  }, [applicationId]);

  if (!application) return <div>Loading...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">
            {application.student.name} - {application.program.name}
          </h1>
          <div className="flex gap-2 mt-2">
            <StatusBadge status={application.status} />
            <StatusBadge status={application.i20Status} />
          </div>
        </div>
        <div className="flex gap-2">
          {application.status === 'eligible' && (
            <Button>Generate I-20</Button>
          )}
          {application.status === 'needs_verification' && (
            <Button>Approve</Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="transcript">Linked Transcript</TabsTrigger>
          <TabsTrigger value="decision">Decision Trace</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="notes">Notes & Review</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardHeader>
              <CardTitle>Applicant Information</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Name</p>
                  <p className="font-medium">{application.student.name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Email</p>
                  <p className="font-medium">{application.student.email}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Program</p>
                  <p className="font-medium">{application.program.name}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">GPA</p>
                  <p className="font-medium">{application.transcript.gpa}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Applied Date</p>
                  <p className="font-medium">{new Date(application.appliedAt).toLocaleDateString()}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Status</p>
                  <StatusBadge status={application.status} />
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="transcript">
          <Card>
            <CardHeader>
              <CardTitle>Linked Transcript</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">
                Transcript from {application.transcript.institution.name}
              </p>
              <Button variant="outline" className="mt-4">
                View Full Transcript
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="decision">
          <Card>
            <CardHeader>
              <CardTitle>Decision Trace</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex items-center gap-2 p-3 border rounded-lg">
                  <StatusBadge status="pass" />
                  <span>GPA Requirement Met</span>
                </div>
                <div className="flex items-center gap-2 p-3 border rounded-lg">
                  <StatusBadge status="pass" />
                  <span>Prerequisites Satisfied</span>
                </div>
                <div className="flex items-center gap-2 p-3 border rounded-lg">
                  <StatusBadge status="warning" />
                  <span>Manual Review: {application.evaluationSummary}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="documents">
          <Card>
            <CardHeader>
              <CardTitle>Required Documents</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {['Transcript', 'Statement of Purpose', 'Letters of Recommendation'].map((doc) => (
                  <div key={doc} className="flex items-center justify-between p-3 border rounded-lg">
                    <span>{doc}</span>
                    <StatusBadge status="active" />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notes">
          <Card>
            <CardHeader>
              <CardTitle>Notes & Manual Review</CardTitle>
            </CardHeader>
            <CardContent>
              <textarea
                className="w-full min-h-[200px] p-3 border rounded-lg"
                placeholder="Add notes..."
              />
              <Button className="mt-4">Add Note</Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

