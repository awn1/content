## Cloudsec AWS automation

In order to configure an instance you need the following requirements:

1. Main Role Configuration

    - Trust Policy: Configure the main role's trust policy to allow the XSOAR engine's EC2 instance to assume it. This is achieved by specifying the EC2 instance profile as a trusted entity with  the following pattern : arn:aws:sts::{{account_id}}:assumed-role/{{main_role_name}}/{{ec2_instance_id}}

    - Permissions Policy: Attach an IAM policy to the main role that permits it to perform the sts:AssumeRole action on each target role. This involves specifying the ARNs of the target roles in the policy's Resource element.

2. Target Role Configuration

    - Role Creation: Create the target role in all AWS accounts where the client intends to run automations. **Ensure that the role name is consistent across all accounts**.


    - Trust Policy: Set the target role's trust policy to allow the main role to assume it. This is done by specifying the main role's ARN in the Principal element of the trust policy. ​


    - Permissions Policy: Attach a permissions policy to the target role that grants access to the specific AWS services required for the automations, such as S3 and EC2.
    The exact permissions should be documented based on the commands that will be implemented.​

3. XSOAR Engine EC2 Instance Configuration

    - Instance Creation: Launch the EC2 instance running the XSOAR engine in the same AWS account as the main role.​

    - IAM Role Association: Assign the main role to the EC2 instance by specifying it in the instance's IAM role configuration. This allows the instance to assume the main role and subsequently the target roles as needed. ​