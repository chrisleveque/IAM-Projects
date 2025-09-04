# Microsoft Entra ID IAM-Project

# Table of Contents

- [Lab 1 Azure Tenant & User Setup](https://github.com/chrisleveque/IAM-Projects/blob/main/README.md#lab-1-azure-tenant--user-setup)
- [Lab 2 Dynamic Groups & RBAC](https://github.com/chrisleveque/IAM-Projects/blob/main/README.md#lab-2-dynamic-groups--rbac)

### Lab 1: Azure Tenant & User Setup 

#### Objective 

Establish a Microsoft Entra ID tenant with baseline IAM configuration. Create organizational units (departments), add test users, and assign initial roles. This provides the foundation for all future IAM/PAM labs. 

#### Pre-requisites 

- Microsoft Azure trial subscription (or access to an existing one) 
- Admin rights in the tenant 
- Microsoft Graph PowerShell module installed 
 

#### Steps Taken 

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






#### Results 

CSV exports of users and groups created successfully. Organizational chart documented. Users assigned to groups and roles per RBAC principles. 

#### Business Value 

This lab demonstrates a structured IAM foundation in Entra ID using RBAC. It shows an understanding of user provisioning, group management, and least privilege role assignment. The setup supports governance, auditing, and access management for future IAM/PAM labs. 


### Lab 2: Dynamic Groups & RBAC 

#### Objective 

Configure dynamic groups and implement Role-Based Access Control (RBAC) in Entra ID to enforce least privilege principles. 

#### Pre-requisites 

- Microsoft Azure/Entra ID tenant access 
- Admin privileges 
- Any specific SaaS apps/tools required for the lab 

#### Steps Taken 

1. Created Dynamic Groups
2. Assigned User Attributes
3. Assigned roles to implement RBAC

#### Screenshots 

Dynamic Group Membership rules
<img width="1920" height="860" alt="Dynamic membership rule HR" src="https://github.com/user-attachments/assets/b0c86491-dbf7-4e2d-bf46-c2f1027f2610" />

HR Group Audit Log
<img width="1920" height="860" alt="HR Group Audit Log" src="https://github.com/user-attachments/assets/211c0e11-fe46-4d7f-83d7-cf6e43d8780c" />

IT Group RBAC
<img width="1920" height="862" alt="IT Group RBAC" src="https://github.com/user-attachments/assets/f1d59693-ca49-4c6b-8835-0599219eec58" />



#### Results 

Dynamic groups were successfully configured based on department attributes. Role assignments were granted via role-assignable groups to demonstrate least privilege enforcement. 

#### Business Value 

This lab shows the ability to automate access control and enforce least privilege, reducing risk of over-provisioned accounts. 
