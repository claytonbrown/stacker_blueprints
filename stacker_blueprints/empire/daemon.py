from troposphere import (
    And,
    Condition,
    Ref,
    Join,
    GetAtt,
    Not,
    Equals,
    If,
    Output,
)
from troposphere import (
    ec2,
    ecs,
    logs,
    sns,
    sqs,
    s3,
)

from troposphere import elasticloadbalancing as elb
from troposphere.route53 import RecordSetType
from troposphere.iam import PolicyType

from stacker.blueprints.base import Blueprint

from .policies import (
    empire_policy,
    sns_to_sqs_policy,
    sns_events_policy,
    runlogs_policy,
)

ELB_SG_NAME = "ELBSecurityGroup"
EVENTS_TOPIC = "EventsTopic"
RUN_LOGS = "RunLogs"


class EmpireDaemon(Blueprint):
    PARAMETERS = {
        "VpcId": {"type": "AWS::EC2::VPC::Id", "description": "Vpc Id"},
        "DefaultSG": {
            "type": "AWS::EC2::SecurityGroup::Id",
            "description": "Top level security group."},
        "ExternalDomain": {
            "type": "String",
            "description": "Base domain for the stack."},
        "PrivateSubnets": {
            "type": "List<AWS::EC2::Subnet::Id>",
            "description": "Subnets to deploy private instances in."},
        "PublicSubnets": {
            "type": "List<AWS::EC2::Subnet::Id>",
            "description": "Subnets to deploy public (elb) instances in."},
        "AvailabilityZones": {
            "type": "CommaDelimitedList",
            "description": "Availability Zones to deploy instances in."},
        "TrustedNetwork": {
            "type": "String",
            "description": "CIDR block allowed to connect to empire ELB."},
        "GitHubCIDR": {
            "type": "String",
            "description": (
                "CIDR Network for for GitHub webhooks (https://goo.gl/D2kZKw)."
            ),
            "default": "192.30.252.0/22"},
        "DatabaseHost": {
            "type": "String",
            "description": "Host for the Empire DB"},
        "DatabaseUser": {
            "type": "String",
            "description": "User for the Empire DB"},
        "DatabasePassword": {
            "type": "String",
            "description": "Password for the Empire DB"},
        "ELBCertName": {
            "type": "String",
            "description": (
                "The SSL certificate name to use on the ELB. Note: If this is"
                " set, non-HTTPS access is disabled."
            ),
            "default": ""},
        "ELBCertType": {
            "type": "String",
            "description": (
                "The SSL certificate type to use on the ELB. Note: Can be"
                " either acm or iam."
            ),
            "default": ""},
        "DesiredCount": {
            "type": "Number",
            "description": "The number of controller tasks to run.",
            "default": "2"},
        "InstanceSecurityGroup": {
            "type": "String",
            "description": "Security group of the controller instances."},
        "InstanceRole": {
            "type": "String",
            "description": "The IAM role to add permissions to."},
        "DockerImage": {
            "type": "String",
            "description": "The docker image to run for the Empire dameon",
            "default": "master"},
        "Environment": {
            "type": "String",
            "description": "Environment used for Empire."},
        "GitHubClientId": {
            "type": "String",
            "description": "EMPIRE_GITHUB_CLIENT_ID",
            "default": ""},
        "GitHubClientSecret": {
            "type": "String",
            "description": "EMPIRE_GITHUB_CLIENT_SECRET",
            "default": ""},
        "GitHubOrganization": {
            "type": "String",
            "description": "EMPIRE_GITHUB_ORGANIZATION",
            "default": ""},
        "GitHubWebhooksSecret": {
            "type": "String",
            "description": "EMPIRE_GITHUB_WEBHOOKS_SECRET",
            "default": ""},
        "GitHubDeploymentsEnvironment": {
            "type": "String",
            "description": (
                "Environment used for GitHub Deployments and honeybadger"
            ),
            "default": ""},
        "TokenSecret": {
            "type": "String",
            "description": "EMPIRE_TOKEN_SECRET",
            "default": ""},
        "TugboatUrl": {
            "type": "String",
            "description": "EMPIRE_TUGBOAT_URL",
            "default": ""},
        "ConveyorUrl": {
            "type": "String",
            "description": "EMPIRE_CONVEYOR_URL",
            "default": ""},
        "LogsStreamer": {
            "type": "String",
            "description": "EMPIRE_LOGS_STREAMER",
            "default": ""},
        "RunLogs": {
            "type": "String",
            "description": "EMPIRE_CLOUDWATCH_LOGS_GROUP",
            "default": ""},
        "Reporter": {
            "type": "String",
            "description": "The reporter to use to report errors",
            "default": ""},
        "InternalZoneId": {
            "type": "String",
            "description": "The ID for the route53 zone for internal DNS"},
        "PrivateAppELBSG": {
            "type": "String",
            "description": (
                "Security group to attach to internal load balancers"
            ),
            "default": ""},
        "PublicAppELBSG": {
            "type": "String",
            "description": "Security group to attach to public load balancers",
            "default": ""},
        "MinionCluster": {
            "type": "String",
            "description": "ECS Cluster for the Minions.",
            "default": ""},
        "ControllerCluster": {
            "type": "String",
            "description": "ECS Cluster for the Controllers.",
            "default": ""},
        "RunLogsBackend": {
            "type": "String",
            "allowed_values": ["cloudwatch", "stdout"],
            "description": "The backend to use for empire run logs.",
            "default": "stdout"},
        "EventsBackend": {
            "type": "String",
            "allowed_values": ["sns", "stdout", ""],
            "description": (
                "The backend to use for empire events. If 'sns' is specified,"
                " provide EventsSNSTopicName to use a specific topic, or else"
                " one will be created for you."
            ),
            "default": "stdout"},
        "EventsSNSTopicName": {
            "type": "String",
            "description": (
                "The SNS topic to use if the 'EventsBackend' is set to 'sns'."
                " If not provided, one will be created for the sns backend."
            ),
            "default": ""},
        "TaskMemory": {
            "type": "Number",
            "description": "The number of MiB to reserve for the task.",
            "default": "1024"},
        "TaskCPU": {
            "type": "Number",
            "description": "The number of CPU units to reserve for the task.",
            "default": "1024"},
        "ServiceMaximumPercent": {
            "type": "Number",
            "description": (
                "The maximum number of tasks, specified as a percentage of the"
                " Amazon ECS service's DesiredCount value, that can run in a"
                " service during a deployment."
            ),
            "default": "100"},
        "ServiceMinimumHealthyPercent": {
            "type": "Number",
            "description": (
                "The minimum number of tasks, specified as a percentage of the"
                " Amazon ECS service's DesiredCount value, that must continue"
                " to run and remain healthy during a deployment."
            ),
            "default": "50"}
    }

    def create_template(self):
        self.create_conditions()
        self.create_security_groups()
        self.create_custom_cloudformation_resources()
        self.create_template_bucket()
        self.create_load_balancer()
        self.create_ecs_resources()
        self.create_log_group()

    def create_conditions(self):
        t = self.template
        ssl_condition = Not(Equals(Ref("ELBCertName"), ""))
        t.add_condition("UseSSL", ssl_condition)
        self.template.add_condition(
            "UseIAMCert",
            Not(Equals(Ref("ELBCertType"), "acm")))
        t.add_condition(
            "EnableSNSEvents",
            Equals(Ref("EventsBackend"), "sns"))
        t.add_condition(
            "CreateSNSTopic",
            And(Equals(Ref("EventsSNSTopicName"), ""),
                Condition("EnableSNSEvents")))
        t.add_condition(
            "EnableCloudwatchLogs",
            Equals(Ref("RunLogsBackend"), "cloudwatch"))

    def create_security_groups(self):
        t = self.template

        t.add_resource(
            ec2.SecurityGroup(
                ELB_SG_NAME,
                GroupDescription="Security group for load balancer",
                VpcId=Ref("VpcId")))
        t.add_resource(
            ec2.SecurityGroupIngress(
                "ELBPort80FromTrustedNetwork",
                IpProtocol="tcp", FromPort="80", ToPort="80",
                CidrIp=Ref("TrustedNetwork"),
                GroupId=Ref(ELB_SG_NAME)))
        t.add_resource(
            ec2.SecurityGroupIngress(
                "ELBPort443FromTrustedNetwork",
                IpProtocol="tcp", FromPort="443", ToPort="443",
                CidrIp=Ref("TrustedNetwork"),
                GroupId=Ref(ELB_SG_NAME)))
        t.add_resource(
            ec2.SecurityGroupIngress(
                "ELBPort443GitHub",
                IpProtocol="tcp", FromPort="443", ToPort="443",
                CidrIp=Ref("GitHubCIDR"),
                GroupId=Ref(ELB_SG_NAME)))
        t.add_resource(
            ec2.SecurityGroupIngress(
                "80ToControllerPort8081",
                IpProtocol="tcp", FromPort="8081", ToPort="8081",
                SourceSecurityGroupId=Ref(ELB_SG_NAME),
                GroupId=Ref("InstanceSecurityGroup")))

    def create_custom_cloudformation_resources(self):
        t = self.template

        queue = sqs.Queue("CustomResourcesQueue")
        topic = sns.Topic(
            "CustomResourcesTopic",
            Subscription=[sns.Subscription(
                Protocol="sqs",
                Endpoint=GetAtt("CustomResourcesQueue", "Arn"))])
        queue_policy = sqs.QueuePolicy(
            "CustomResourcesQueuePolicy",
            Queues=[Ref(queue)],
            PolicyDocument=sns_to_sqs_policy(Ref(topic)))

        t.add_resource(queue)
        t.add_resource(topic)
        t.add_resource(queue_policy)

    def create_template_bucket(self):
        t = self.template
        t.add_resource(s3.Bucket("TemplateBucket"))

    def setup_listeners(self):
        no_ssl = [elb.Listener(
            LoadBalancerPort=80,
            Protocol="TCP",
            InstancePort=8081,
            InstanceProtocol="TCP"
        )]

        acm_cert = Join("", [
            "arn:aws:acm:", Ref("AWS::Region"), ":", Ref("AWS::AccountId"),
            ":certificate/", Ref("ELBCertName")])
        iam_cert = Join("", [
            "arn:aws:iam::", Ref("AWS::AccountId"), ":server-certificate/",
            Ref("ELBCertName")])
        cert_id = If("UseIAMCert", iam_cert, acm_cert)

        with_ssl = []
        with_ssl.append(elb.Listener(
            LoadBalancerPort=443,
            InstancePort=8081,
            Protocol="SSL",
            InstanceProtocol="TCP",
            SSLCertificateId=cert_id))
        listeners = If("UseSSL", with_ssl, no_ssl)

        return listeners

    def create_load_balancer(self):
        t = self.template

        t.add_resource(
            elb.LoadBalancer(
                "LoadBalancer",
                HealthCheck=elb.HealthCheck(
                    Target="HTTP:8081/health",
                    HealthyThreshold=3,
                    UnhealthyThreshold=3,
                    Interval=5,
                    Timeout=3),
                Listeners=self.setup_listeners(),
                SecurityGroups=[Ref(ELB_SG_NAME), ],
                Subnets=Ref("PublicSubnets")))

        # Setup ELB DNS
        t.add_resource(
            RecordSetType(
                "ElbDnsRecord",
                HostedZoneName=Join("", [Ref("ExternalDomain"), "."]),
                Comment="Router ELB DNS",
                Name=Join(".", ["empire", Ref("ExternalDomain")]),
                Type="CNAME",
                TTL="120",
                ResourceRecords=[GetAtt("LoadBalancer", "DNSName")]))

    def get_empire_environment(self):
        database_url = Join("", [
            "postgres://", Ref("DatabaseUser"), ":",
            Ref("DatabasePassword"), "@", Ref("DatabaseHost"), "/empire"])
        return [
            ecs.Environment(
                Name="EMPIRE_ENVIRONMENT",
                Value=Ref("Environment")),
            ecs.Environment(
                Name="EMPIRE_SCHEDULER",
                Value="cloudformation-migration"),
            ecs.Environment(
                Name="EMPIRE_REPORTER",
                Value=Ref("Reporter")),
            ecs.Environment(
                Name="EMPIRE_S3_TEMPLATE_BUCKET",
                Value=Ref("TemplateBucket")),
            ecs.Environment(
                Name="EMPIRE_GITHUB_CLIENT_ID",
                Value=Ref("GitHubClientId")),
            ecs.Environment(
                Name="EMPIRE_GITHUB_CLIENT_SECRET",
                Value=Ref("GitHubClientSecret")),
            ecs.Environment(
                Name="EMPIRE_DATABASE_URL",
                Value=database_url),
            ecs.Environment(
                Name="EMPIRE_TOKEN_SECRET",
                Value=Ref("TokenSecret")),
            ecs.Environment(
                Name="AWS_REGION",
                Value=Ref("AWS::Region")),
            ecs.Environment(
                Name="EMPIRE_PORT",
                Value="8081"),
            ecs.Environment(
                Name="EMPIRE_GITHUB_ORGANIZATION",
                Value=Ref("GitHubOrganization")),
            ecs.Environment(
                Name="EMPIRE_GITHUB_WEBHOOKS_SECRET",
                Value=Ref("GitHubWebhooksSecret")),
            ecs.Environment(
                Name="EMPIRE_GITHUB_DEPLOYMENTS_ENVIRONMENT",
                Value=Ref("GitHubDeploymentsEnvironment")),
            ecs.Environment(
                Name="EMPIRE_EVENTS_BACKEND",
                Value=Ref("EventsBackend")),
            ecs.Environment(
                Name="EMPIRE_SNS_TOPIC",
                Value=If(
                    "EnableSNSEvents",
                    If("CreateSNSTopic",
                       Ref(EVENTS_TOPIC),
                       Ref("EventsSNSTopicName")),
                    "AWS::NoValue")),
            ecs.Environment(
                Name="EMPIRE_TUGBOAT_URL",
                Value=Ref("TugboatUrl")),
            ecs.Environment(
                Name="EMPIRE_LOGS_STREAMER",
                Value=Ref("LogsStreamer")),
            ecs.Environment(
                Name="EMPIRE_ECS_CLUSTER",
                Value=Ref("MinionCluster")),
            ecs.Environment(
                Name="EMPIRE_ECS_SERVICE_ROLE",
                Value="ecsServiceRole"),
            ecs.Environment(
                Name="EMPIRE_ROUTE53_INTERNAL_ZONE_ID",
                Value=Ref("InternalZoneId")),
            ecs.Environment(
                Name="EMPIRE_EC2_SUBNETS_PRIVATE",
                Value=Join(",", Ref("PrivateSubnets"))),
            ecs.Environment(
                Name="EMPIRE_EC2_SUBNETS_PUBLIC",
                Value=Join(",", Ref("PublicSubnets"))),
            ecs.Environment(
                Name="EMPIRE_ELB_SG_PRIVATE",
                Value=Ref("PrivateAppELBSG")),
            ecs.Environment(
                Name="EMPIRE_ELB_SG_PUBLIC",
                Value=Ref("PublicAppELBSG")),
            ecs.Environment(
                Name="EMPIRE_GITHUB_DEPLOYMENTS_IMAGE_BUILDER",
                Value="conveyor"),
            ecs.Environment(
                Name="EMPIRE_CONVEYOR_URL",
                Value=Ref("ConveyorUrl")),
            ecs.Environment(
                Name="EMPIRE_RUN_LOGS_BACKEND",
                Value=Ref("RunLogsBackend")),
            ecs.Environment(
                Name="EMPIRE_CUSTOM_RESOURCES_TOPIC",
                Value=Ref("CustomResourcesTopic")),
            ecs.Environment(
                Name="EMPIRE_CUSTOM_RESOURCES_QUEUE",
                Value=Ref("CustomResourcesQueue")),
            ecs.Environment(
                Name="EMPIRE_CLOUDWATCH_LOG_GROUP",
                Value=If(
                    "EnableCloudwatchLogs",
                    Ref(RUN_LOGS),
                    "AWS::NoValue")),
        ]

    def create_ecs_resources(self):
        t = self.template

        # Give the instances access that the Empire daemon needs.
        t.add_resource(
            PolicyType(
                "AccessPolicy",
                PolicyName="empire",
                PolicyDocument=empire_policy({
                    "Environment": Ref("Environment"),
                    "CustomResourcesTopic": Ref("CustomResourcesTopic"),
                    "CustomResourcesQueue": (
                        GetAtt("CustomResourcesQueue", "Arn")
                    ),
                    "TemplateBucket": (
                        Join("", ["arn:aws:s3:::", Ref("TemplateBucket"), "/*"])
                    )}),
                Roles=[Ref("InstanceRole")]))

        t.add_resource(sns.Topic(
            EVENTS_TOPIC,
            DisplayName="Empire events",
            Condition="CreateSNSTopic",
        ))
        t.add_resource(
            Output(
                "EventsSNSTopic",
                Value=Ref(EVENTS_TOPIC),
                Condition="CreateSNSTopic"))

        # Add SNS Events policy if Events are enabled
        t.add_resource(
            PolicyType(
                "SNSEventsPolicy",
                PolicyName="EmpireSNSEventsPolicy",
                Condition="EnableSNSEvents",
                PolicyDocument=sns_events_policy(
                    If("CreateSNSTopic",
                       Ref(EVENTS_TOPIC),
                       Ref("EventsSNSTopicName"))),
                Roles=[Ref("InstanceRole")]))

        # Add run logs policy if run logs are enabled
        t.add_resource(
            PolicyType(
                "RunLogsPolicy",
                PolicyName="EmpireRunLogsPolicy",
                Condition="EnableCloudwatchLogs",
                PolicyDocument=runlogs_policy(Ref(RUN_LOGS)),
            ))

        t.add_resource(
            ecs.TaskDefinition(
                "TaskDefinition",
                Volumes=[
                    ecs.Volume(
                        Name="dockerSocket",
                        Host=ecs.Host(SourcePath="/var/run/docker.sock")),
                    ecs.Volume(
                        Name="dockerCfg",
                        Host=ecs.Host(SourcePath="/root/.dockercfg"))],
                ContainerDefinitions=[
                    ecs.ContainerDefinition(
                        Command=["server", "-automigrate=true"],
                        Name="empire",
                        Environment=self.get_empire_environment(),
                        Essential=True,
                        Image=Ref("DockerImage"),
                        MountPoints=[
                            ecs.MountPoint(
                                SourceVolume="dockerSocket",
                                ContainerPath="/var/run/docker.sock",
                                ReadOnly=False),
                            ecs.MountPoint(
                                SourceVolume="dockerCfg",
                                ContainerPath="/root/.dockercfg",
                                ReadOnly=False)],
                        PortMappings=[
                            ecs.PortMapping(
                                HostPort=8081,
                                ContainerPort=8081)],
                        Cpu=Ref("TaskCPU"),
                        Memory=Ref("TaskMemory"))]))

        t.add_resource(
            ecs.Service(
                "Service",
                Cluster=Ref("ControllerCluster"),
                DeploymentConfiguration=ecs.DeploymentConfiguration(
                    MaximumPercent=Ref("ServiceMaximumPercent"),
                    MinimumHealthyPercent=Ref("ServiceMinimumHealthyPercent"),
                ),
                DesiredCount=Ref("DesiredCount"),
                LoadBalancers=[
                    ecs.LoadBalancer(
                        ContainerName="empire",
                        ContainerPort=8081,
                        LoadBalancerName=Ref("LoadBalancer"))],
                Role="ecsServiceRole",
                TaskDefinition=Ref("TaskDefinition")))

    def create_log_group(self):
        t = self.template
        t.add_resource(logs.LogGroup(RUN_LOGS, Condition="EnableRunLogs"))
        t.add_output(
            Output("RunLogs", Value=Ref(RUN_LOGS), Condition="EnableRunLogs"))
