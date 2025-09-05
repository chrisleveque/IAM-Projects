# Microsoft Entra ID IAM-Project

# Table of Contents

- [Lab 1: Azure Tenant & User Setup](https://github.com/chrisleveque/IAM-Projects/blob/main/README.md#lab-1-azure-tenant--user-setup)
- [Lab 2: Dynamic Groups & RBAC](https://github.com/chrisleveque/IAM-Projects/blob/main/README.md#lab-2-dynamic-groups--rbac)
- [Lab 3: User Lifecycle Management (Joiner-Mover-Leaver)](https://github.com/chrisleveque/IAM-Projects/blob/main/README.md#lab-3-user-lifecycle-joiner-mover-leaver)
# Lab 1: Azure Tenant & User Setup 

## Objective 

Establish a Microsoft Entra ID tenant with baseline IAM configuration. Create organizational units (departments), add test users, and assign initial roles. This provides the foundation for all future IAM/PAM labs. 

## Pre-requisites 

- Microsoft Azure trial subscription (or access to an existing one) 
- Admin rights in the tenant 
- Microsoft Graph PowerShell module installed 
 

## Steps Taken 

1. Created Security Groups for departments (IT, HR, Finance, Contractors). 

2. Created test users (Alice Johnson, Bob Smith, Carol Martinez, David Lee, Eve Thompson). 

3. Assigned users to appropriate groups. 

4. Assigned initial Entra ID roles (User Administrator, Security Reader). 

5. Exported user and group membership for documentation. 

Screenshots 

Carol Assigned Role
<img width="1915" height="914" alt="Carol Martinez Assigned Role" src="https://github.com/user-attachments/assets/bf532d8c-ce9c-4a39-bb46-4d42bd4f6295" />

Eve Assigned Role
<img width="1920" height="910" alt="Eve Thompson Assigned Role" src="https://github.com/user-attachments/assets/4f77a36c-57bb-4ced-9ce1-7b15da27cc4c" />

Group List
<img width="1918" height="914" alt="Security Groups" src="https://github.com/user-attachments/assets/b24bb3b8-4425-4f83-b72b-70c309a02f48" />

User List
<img width="1920" height="914" alt="User List" src="https://github.com/user-attachments/assets/19f436de-a1e9-48ff-82d4-8ea59f8e24b4" />






## Results 

CSV exports of users and groups created successfully. Organizational chart documented. Users assigned to groups and roles per RBAC principles. 

## Business Value 

This lab demonstrates a structured IAM foundation in Entra ID using RBAC. It shows an understanding of user provisioning, group management, and least privilege role assignment. The setup supports governance, auditing, and access management for future IAM/PAM labs. 


# Lab 2: Dynamic Groups & RBAC 

## Objective 

Configure dynamic groups and implement Role-Based Access Control (RBAC) in Entra ID to enforce least privilege principles. 

## Pre-requisites 

- Microsoft Azure/Entra ID tenant access 
- Admin privileges 
- Any specific SaaS apps/tools required for the lab 

## Steps Taken 

1. Created Dynamic Groups
2. Assigned User Attributes
3. Assigned roles to implement RBAC

## Screenshots 

Dynamic Group Membership rules
<img width="1920" height="860" alt="Dynamic membership rule HR" src="https://github.com/user-attachments/assets/b0c86491-dbf7-4e2d-bf46-c2f1027f2610" />

HR Group Audit Log
<img width="1920" height="860" alt="HR Group Audit Log" src="https://github.com/user-attachments/assets/211c0e11-fe46-4d7f-83d7-cf6e43d8780c" />

IT Group RBAC
<img width="1920" height="862" alt="IT Group RBAC" src="https://github.com/user-attachments/assets/f1d59693-ca49-4c6b-8835-0599219eec58" />



## Results 

Dynamic groups were successfully configured based on department attributes. Role assignments were granted via role-assignable groups to demonstrate least privilege enforcement. 

## Business Value 

This lab shows the ability to automate access control and enforce least privilege, reducing risk of over-provisioned accounts. 

# Lab 3: User Lifecycle (Joiner-Mover-Leaver) 

## Objective 

Automate user provisioning, group assignments, and deprovisioning using Entra ID dynamic groups and SaaS app integrations. 

## Pre-requisites 

- Microsoft Azure/Entra ID tenant access 
- Admin privileges
- Dynamic Groups
- Salesforce Account(free trial)

## Steps Taken 

1. Configured Automatic Provisioning
2. Added new user Jane Doe (Joiner)
3. Verified Salesforce account was auto-provisioned
4. Added more users to Salesforce confirming no provisioning errors
5. Edited the user attribute for John Doe from Finance to HR
6. Verified user was removed from Finance Group and added to the HR Group (mover)
7. Disabled John's account
8. Verified John's Salesforce account was automatically removed
 

## Screenshots 

<img width="1920" height="912" alt="Jane Doe Salesforce Provisioning" src="https://github.com/user-attachments/assets/5c4200c0-53da-4073-b1fe-203a36f2917c" />

<img width="1915" height="862" alt="Provisioning Logs - Create" src="https://github.com/user-attachments/assets/ddac850b-71e0-4393-9837-fe6fc149405d" />

<img width="1920" height="862" alt="John Doe's Group Before Moving" src="https://github.com/user-attachments/assets/7f09fb7c-d98c-4745-a979-ae4764f84c79" />

<img width="1920" height="1020" alt="John Doe Attribute Change" src="https://github.com/user-attachments/assets/f3ea8dd4-f6d1-45a8-ab33-ff3847382098" />

<img width="1920" height="859" alt="Finance Group Audit Log 1" src="https://github.com/user-attachments/assets/72052f4f-9e9f-45f6-b399-61602b53c502" />

<img width="1920" height="857" alt="Finance Group Audit Log 2 " src="https://github.com/user-attachments/assets/fdbc4e5c-4f76-474a-896d-75904610ae15" />

<img width="1920" height="865" alt="HR Audit Log 1" src="https://github.com/user-attachments/assets/7305e1b5-1f53-49d9-8a91-eac1a14d387d" />

<img width="1920" height="863" alt="HR Audit Log 2" src="https://github.com/user-attachments/assets/5ed6c7ee-1957-44a5-9f3b-43c0c147e2eb" />

<img width="1920" height="860" alt="John Doe Disabled" src="https://github.com/user-attachments/assets/6e1b1e94-c9c3-4427-ad04-9a0e06398be1" />

<img width="1920" height="862" alt="John Doe Provisioning Logs" src="https://github.com/user-attachments/assets/966682eb-57d8-4e05-bb7a-5fc51f1d7856" />

## Results 

User lifecycle automation was demonstrated by provisioning a user into Salesforce, assigning groups dynamically, and ensuring account deprovisioning upon termination. 

## Business Value 

This lab highlights identity lifecycle governance, ensuring timely onboarding/offboarding and reducing orphan accounts. 

# Lab 4: Access Reviews (UAR Campaign) 

## Objective 

Configure User Access Review campaigns to ensure users maintain appropriate levels of access. 

## Pre-requisites 

- Identity Governance free trial

Steps Taken 

1. Setup Identity Governance free trial 
2. Configure User Access Review
3. Once configured, log in with the selected member to approve/deny at https://myaccess.microsoft.com/
4. Approve/Deny selected users

## Screenshots 

<img width="1920" height="858" alt="UAR Settings 1" src="https://github.com/user-attachments/assets/128eee00-20e9-4dd1-8528-794ae30f9d66" />

<img width="1918" height="862" alt="UAR Settings 2" src="https://github.com/user-attachments/assets/b9b84f57-8d99-4d58-955a-681dcf152b97" />

<img width="1920" height="861" alt="UAR Settings 3" src="https://github.com/user-attachments/assets/73385997-cbb5-478d-b153-9674225a8432" />

<img width="1918" height="858" alt="UAR Settings 4" src="https://github.com/user-attachments/assets/bd5432b7-ba58-476e-a5ce-b783e8e9511b" />

<img width="1920" height="911" alt="UAR Before Approval" src="https://github.com/user-attachments/assets/73b3962a-b1b9-46d8-89ba-d26cd3686eda" />

<img width="1920" height="907" alt="UAR Approval" src="https://github.com/user-attachments/assets/d610ecac-7286-4f17-86d3-07dc7a5bf86c" />


## Results 

An access review campaign was successfully created for managers to validate their direct reports' access rights. 

## Business Value 

This lab showcases governance and compliance readiness by ensuring periodic validation of user access. 

