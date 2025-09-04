# Microsoft Entra ID IAM-Project

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


<img width="1915" height="914" alt="Carol Martinez Assigned Role" src="https://github.com/user-attachments/assets/bf532d8c-ce9c-4a39-bb46-4d42bd4f6295" />

<img width="1920" height="910" alt="Eve Thompson Assigned Role" src="https://github.com/user-attachments/assets/4f77a36c-57bb-4ced-9ce1-7b15da27cc4c" />

<img width="1918" height="914" alt="Security Groups" src="https://github.com/user-attachments/assets/b24bb3b8-4425-4f83-b72b-70c309a02f48" />

<img width="1920" height="914" alt="User List" src="https://github.com/user-attachments/assets/19f436de-a1e9-48ff-82d4-8ea59f8e24b4" />






#### Results 

CSV exports of users and groups created successfully. Organizational chart documented. Users assigned to groups and roles per RBAC principles. 

#### Business Value 

This lab demonstrates a structured IAM foundation in Entra ID using RBAC. It shows an understanding of user provisioning, group management, and least privilege role assignment. The setup supports governance, auditing, and access management for future IAM/PAM labs. 
