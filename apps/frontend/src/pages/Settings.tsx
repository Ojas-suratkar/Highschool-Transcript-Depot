import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Bell, Lock, Database, Globe, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';

export default function Settings() {
  const { toast } = useToast();
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [transcriptAlerts, setTranscriptAlerts] = useState(true);
  const [admissionAlerts, setAdmissionAlerts] = useState(true);
  const [twoFactorAuth, setTwoFactorAuth] = useState(false);

  const handleSave = () => {
    toast({
      title: 'Settings saved',
      description: 'Your preferences have been updated successfully',
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Configure system preferences and integrations</p>
      </div>

      {/* Notifications */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            Notifications
          </CardTitle>
          <CardDescription>Manage how you receive notifications</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Email Notifications</Label>
              <p className="text-sm text-muted-foreground">Receive email updates about system activity</p>
            </div>
            <Switch checked={emailNotifications} onCheckedChange={setEmailNotifications} />
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Transcript Processing Alerts</Label>
              <p className="text-sm text-muted-foreground">Get notified when transcripts are processed</p>
            </div>
            <Switch checked={transcriptAlerts} onCheckedChange={setTranscriptAlerts} />
          </div>
          <Separator />
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Admission Decision Alerts</Label>
              <p className="text-sm text-muted-foreground">Get notified about admission decisions</p>
            </div>
            <Switch checked={admissionAlerts} onCheckedChange={setAdmissionAlerts} />
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lock className="h-5 w-5" />
            Security
          </CardTitle>
          <CardDescription>Manage your account security settings</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Two-Factor Authentication</Label>
              <p className="text-sm text-muted-foreground">Add an extra layer of security to your account</p>
            </div>
            <Switch checked={twoFactorAuth} onCheckedChange={setTwoFactorAuth} />
          </div>
          <Separator />
          <div className="space-y-2">
            <Label>Change Password</Label>
            <div className="grid gap-2">
              <Input type="password" placeholder="Current password" />
              <Input type="password" placeholder="New password" />
              <Input type="password" placeholder="Confirm new password" />
              <Button variant="outline" size="sm" className="w-fit">
                Update Password
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Integrations */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-5 w-5" />
            Integrations
          </CardTitle>
          <CardDescription>Connect with external services</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>UC Doorway API Key</Label>
            <Input type="password" placeholder="Enter your UC Doorway API key" />
            <p className="text-xs text-muted-foreground">
              Required for automatic course validation
            </p>
          </div>
          <Separator />
          <div className="space-y-2">
            <Label>Email Delivery</Label>
            <p className="text-sm text-muted-foreground">Email delivery is handled via Brevo (Sendinblue) or the local mock sender for development.</p>
          </div>
        </CardContent>
      </Card>

      {/* Data Management */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Data Management
          </CardTitle>
          <CardDescription>Manage your data and backups</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label>Automatic Backups</Label>
              <p className="text-sm text-muted-foreground">Daily backups of all system data</p>
            </div>
            <Switch defaultChecked />
          </div>
          <Separator />
          <div className="flex gap-2">
            <Button variant="outline" size="sm">
              <Database className="h-4 w-4 mr-2" />
              Export All Data
            </Button>
            <Button variant="outline" size="sm">
              <Database className="h-4 w-4 mr-2" />
              Create Backup
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button onClick={handleSave} className="gap-2 bg-[#3B5BDB] hover:bg-[#2E4AC4]">
          <Save className="h-4 w-4" />
          Save All Settings
        </Button>
      </div>
    </div>
  );
}

