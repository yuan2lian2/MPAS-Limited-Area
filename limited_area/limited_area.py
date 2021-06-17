from __future__ import absolute_import, division, print_function
import argparse
import os
import sys

import numpy as np

from limited_area.mesh import MeshHandler
from limited_area.mesh import latlon_to_xyz
from limited_area.mesh import sphere_distance
from limited_area.region_spec import RegionSpec

class LimitedArea():
    """ Facilitate creating a regional MPAS mesh from a global MPAS mesh  """
    num_boundary_layers = 8
    INSIDE = 1
    UNMARKED = 0

    def __init__(self,
                 files,
                 region,
                 regionFormat='points',
                 format='NETCDF3_64BIT_OFFSET',
                 *args,
                 **kwargs):
        """ Init function for Limited Area

        Check to see if all mesh files that were passed in to files exist
        and that they are all the correct type. Check to see if the first
        (or only) file contains mesh connectivity. If it is, then load its
        connectivity fields.

        Add the mesh connectivity mesh to self.mesh, and then add all meshes
        to the self.meshes attribute. Thus, we can use self.mesh to subset all
        meshes in the self.meshes attribute in gen_region.

        Keyword arguments:
        files        -- Path to valid MPAS mesh files. If multiple files are given, the first file
                        must contain mesh connectivity information, which will be used to subset
                        itself, and all following files.
        region       -- Path to pts file region specification 

        DEBUG         -- Debug value used to turn on debug output, default == 0
        markNeighbors -- Algorithm choice for choosing relaxation layers - Default
                         is mark neighbor search
        """ 

        self.meshes = []

        # Keyword arguments
        self._DEBUG_ = kwargs.get('DEBUG', 0)
        self.boundary = kwargs.get('markNeighbors', 'search')
        self.cdf_format = format

        # Check to see the points file exists and if it exists, then parse it
        # and see that is is specified correctly!
        self.region_file = region
        self.regionSpec = RegionSpec(*args, **kwargs)

        # Choose the algorithm to mark relaxation region
        if self.boundary == None:
            # Possibly faster for larger regions
            self.mark_neighbors = self._mark_neighbors
        elif self.boundary == 'search':
            # Possibly faster for smaller regions
            self.mark_neighbors = self._mark_neighbors_search

        # Check to see that all given mesh files, simply exist
        for mesh in files:
            if not os.path.isfile(mesh):
                print("ERROR: Mesh file was not found", mesh_file)
                sys.exit(-1)

        if len(files) == 1:
            self.mesh = MeshHandler(files[0], 'r', *args, **kwargs)
            if self.mesh.check_grid():
                self.mesh.load_vars()
            else:
                print("ERROR:", self.mesh.fname, "did not contain needed mesh connectivity information")
                sys.exit(-1)
            self.meshes.append(self.mesh)

        else:
            self.mesh = MeshHandler(files.pop(0), 'r', *args, **kwargs)
            if self.mesh.check_grid():
                # Load the mesh connectivity variables needed to subset this mesh, and all the
                # other ones
                self.mesh.load_vars()
                self.meshes.append(self.mesh)
            else:
                print("ERROR:", self.mesh.fname, "did not contain needed mesh connectivity information")
                print("ERROR: The first file must contain mesh connectivity information")
                sys.exit(-1)

            for mesh in files:
                self.meshes.append(MeshHandler(mesh, 'r', *args, **kwargs))

    def gen_region(self, *args, **kwargs):
        """ Generate the boundary region of the specified region
        and subset meshes in self.meshes """

        # Call the regionSpec to generate `name, in_point, boundaries`
        name, inPoint, boundaries= self.regionSpec.gen_spec(self.region_file, **kwargs)

        if self._DEBUG_ > 0:
            print("DEBUG: Region Spec has been generated")
            print("DEBUG: Region Name: ", name)
            print("DEBUG: In Point: ", inPoint)
            print("DEBUG: # of boundaries: ", len(boundaries))

        # For each mesh, create a regional mesh and save it
        print('\n')
        # TODO: Update this print statement to be more consistent to what is happening
        print('Creating a regional mesh of ', self.mesh.fname)

        # Mark boundaries
        # A specification may have multiple, discontiguous boundaries,
        # so, create a unmarked, filled bdyMaskCell and pass it to
        # mark_boundary for each boundary.
        print('Marking ', end=''); sys.stdout.flush()
        bdyMaskCell = np.full(self.mesh.nCells, self.UNMARKED)
        i = 1
        for boundary in boundaries:
            print("boundary ", i, "... ", end=''); sys.stdout.flush(); i += 1
            bdyMaskCell = self.mark_boundary(self.mesh, boundary, bdyMaskCell)

        # Find the nearest cell to the inside point
        inCell = self.mesh.nearest_cell(inPoint[0], inPoint[1])

        # Flood fill from the inside point
        print('\nFilling region ...')
        bdyMaskCell = self.flood_fill(self.mesh, inCell, bdyMaskCell)

        # Mark the neighbors
        print('Creating boundary layer:', end=' '); sys.stdout.flush()
        for layer in range(1, self.num_boundary_layers + 1):
            print(layer, ' ...', end=' '); sys.stdout.flush()
            self.mark_neighbors(self.mesh, layer, bdyMaskCell, inCell=inCell)
        print('DONE!')

        if self._DEBUG_ > 2:
            print("DEBUG: bdyMaskCells count:")
            print("DEBUG: 0: ", len(bdyMaskCell[bdyMaskCell == 0]))
            print("DEBUG: 1: ", len(bdyMaskCell[bdyMaskCell == 1]))
            print("DEBUG: 2: ", len(bdyMaskCell[bdyMaskCell == 2]))
            print("DEBUG: 3: ", len(bdyMaskCell[bdyMaskCell == 3]))
            print("DEBUG: 4: ", len(bdyMaskCell[bdyMaskCell == 4]))
            print("DEBUG: 5: ", len(bdyMaskCell[bdyMaskCell == 5]))
            print("DEBUG: 6: ", len(bdyMaskCell[bdyMaskCell == 6]))
            print("DEBUG: 7: ", len(bdyMaskCell[bdyMaskCell == 7]))
            print("DEBUG: 8: ", len(bdyMaskCell[bdyMaskCell == 8]))
            print('\n')

        bdyMaskCell_cp = bdyMaskCell

        # Mark the edges
        print('Marking region edges ...')
        bdyMaskEdge = self.mark_edges(self.mesh,
                                      bdyMaskCell,
                                      *args,
                                      **kwargs)

        # Mark the vertices
        print('Marking region vertices...')
        bdyMaskVertex = self.mark_vertices(self.mesh,
                                           bdyMaskCell,
                                           *args,
                                           **kwargs)


        # Create subsets of all the meshes in self.meshes
        print('Subsetting meshes...')
        for mesh in self.meshes:
            print("\nSubsetting:", mesh.fname)

            regionFname = self.create_regional_fname(name, mesh.fname)
            regionalMesh = mesh.subset_fields(regionFname,
                                              bdyMaskCell,
                                              bdyMaskEdge,
                                              bdyMaskVertex,
                                              self.INSIDE,
                                              self.UNMARKED,
                                              self.mesh,
                                              format=self.cdf_format,
                                              *args,
                                              **kwargs)
            print("Copying global attributes... ")
            regionalMesh.copy_global_attributes(self.mesh)
            print("Create a regional mesh:", regionFname)

            if mesh.check_grid():
                # Save the regional mesh that contains graph connectivity to create the regional
                # graph partition file below
                regionalMeshConn = regionalMesh
            else:
                regionalMesh.mesh.close()
                mesh.mesh.close()


        print('Creating graph partition file...', end=' '); sys.stdout.flush()
        graphFname = regionalMeshConn.create_graph_file(self.create_partiton_fname(name, self.mesh,))
        print(graphFname)

        regionalMeshConn.mesh.close()

        return regionFname, graphFname

    def create_partiton_fname(self, name, mesh, **kwargs):
        """ Generate the filename for the regional graph.info file"""
        return name+'.graph.info'
        

    def create_regional_fname(self, regionName, meshFileName, **kwargs):
        """ Create the regional file name by prepending the regional name
        (specified by Name: ) in the points file, to the meshFileName. """
        return regionName+'.'+os.path.basename(meshFileName)


    # Mark_neighbors_search - Faster for smaller regions ??
    def _mark_neighbors_search(self, mesh, layer, bdyMaskCell, *args, **kwargs):
        """ Mark the relaxation layers using a search and return an updated bdyMaskCell with
        those relaxation layers
        
        mesh        -- The global MPAS mesh
        layer       -- The relaxation layer
        bdyMaskCell -- The global mask marking the regional cell subset
        inCell      -- A point that is inside the regional area

        """
        inCell = kwargs.get('inCell', None)
        if inCell == None:
            print("ERROR: In cell not found within _mark_neighbors_search")

        stack = [inCell]
        while len(stack) > 0:
            iCell = stack.pop()
            for i in range(mesh.nEdgesOnCell[iCell]):
                j = mesh.cellsOnCell[iCell, i] - 1
                if layer > bdyMaskCell[j] >= self.INSIDE:
                    bdyMaskCell[j] = -bdyMaskCell[j]
                    stack.append(j)
                elif bdyMaskCell[j] == 0:
                    bdyMaskCell[j] = layer 

        bdyMaskCell[:] = abs(bdyMaskCell[:])


    # mark_neighbors - Faster for larger regions ??
    def _mark_neighbors(self, mesh, nType, bdyMaskCell, *args, **kwargs):
        """ Mark a relaxation layers of nType

        mesh        -- The global MPAS mesh
        nType       -- The current relaxation cell that will be marked on bdyMaskCell
        bdyMaskCell -- The global mask marking the regional cell subset
        """

        for iCell in range(mesh.nCells):
            if bdyMaskCell[iCell] == self.UNMARKED:
                for i in range(mesh.nEdgesOnCell[iCell]):
                    v = mesh.cellsOnCell[iCell, i] - 1
                    if bdyMaskCell[v] == 0:
                        bdyMaskCell[v] == nType


    def flood_fill(self, mesh, inCell, bdyMaskCell):
        """ Mark the interior points of the regional mesh and return and updated
        bdyMaskCell.

        mesh        -- Global MPAS Mesh
        inCell      -- A point that is inside the specified region
        bdyMaskCell -- The global mask marking which global cells are interior, relaxation
                       and those that are outside.
        """
        if self._DEBUG_ > 1:
            print("DEBUG: Flood filling with flood_fill")

        stack = [inCell]
        while len(stack) > 0:
            iCell = stack.pop()
            for i in range(mesh.nEdgesOnCell[iCell]):
                j = mesh.cellsOnCell[iCell, i] - 1
                if bdyMaskCell[j] == self.UNMARKED:
                    bdyMaskCell[j] = self.INSIDE
                    stack.append(j)

        return bdyMaskCell


    def mark_edges(self, mesh, bdyMaskCell, *args, **kwargs):
        """ Mark the edges that are in the specified region and return
        bdyMaskEdge. """

        bdyMaskEdge = bdyMaskCell[mesh.cellsOnEdge[:,:]-1].min(axis=1)
        bdyMaskEdge = np.where(bdyMaskEdge > 0,
                               bdyMaskEdge,
                               bdyMaskCell[mesh.cellsOnEdge[:,:]-1].max(axis=1))

        if self._DEBUG_ > 2:
            print("DEBUG: bdyMaskEdges count:")
            print("DEBUG: 0: ", len(bdyMaskEdge[bdyMaskEdge == 0]))
            print("DEBUG: 1: ", len(bdyMaskEdge[bdyMaskEdge == 1]))
            print("DEBUG: 2: ", len(bdyMaskEdge[bdyMaskEdge == 2]))
            print("DEBUG: 3: ", len(bdyMaskEdge[bdyMaskEdge == 3]))
            print("DEBUG: 4: ", len(bdyMaskEdge[bdyMaskEdge == 4]))
            print("DEBUG: 5: ", len(bdyMaskEdge[bdyMaskEdge == 5]))
            print("DEBUG: 6: ", len(bdyMaskEdge[bdyMaskEdge == 6]))
            print("DEBUG: 7: ", len(bdyMaskEdge[bdyMaskEdge == 7]))
            print("DEBUG: 8: ", len(bdyMaskEdge[bdyMaskEdge == 8]))
            print('\n')

        return bdyMaskEdge


    def mark_vertices(self, mesh, bdyMaskCell, *args, **kwargs):
        """ Mark the vertices that are in the spefied region and return
        bdyMaskVertex."""

        bdyMaskVertex = bdyMaskCell[mesh.cellsOnVertex[:,:]-1].min(axis=1)
        bdyMaskVertex = np.where(bdyMaskVertex > 0,
                                 bdyMaskVertex,
                                 bdyMaskCell[mesh.cellsOnVertex[:,:]-1].max(axis=1))

        if self._DEBUG_ > 2:
            print("DEBUG: bdyMaskVertex count:")
            print("DEBUG: 0: ", len(bdyMaskVertex[bdyMaskVertex == 0]))
            print("DEBUG: 1: ", len(bdyMaskVertex[bdyMaskVertex == 1]))
            print("DEBUG: 2: ", len(bdyMaskVertex[bdyMaskVertex == 2]))
            print("DEBUG: 3: ", len(bdyMaskVertex[bdyMaskVertex == 3]))
            print("DEBUG: 4: ", len(bdyMaskVertex[bdyMaskVertex == 4]))
            print("DEBUG: 5: ", len(bdyMaskVertex[bdyMaskVertex == 5]))
            print("DEBUG: 6: ", len(bdyMaskVertex[bdyMaskVertex == 6]))
            print("DEBUG: 7: ", len(bdyMaskVertex[bdyMaskVertex == 7]))
            print("DEBUG: 8: ", len(bdyMaskVertex[bdyMaskVertex == 8]))
            print('\n')

        return bdyMaskVertex
    

    # Mark Boundary points
    def mark_boundary(self, mesh, points, bdyMaskCell, *args, **kwargs):
        """ Mark the nearest cell to each of the cords in points
        as a boundary cell and return bdyMaskCell.

        mesh - The global mesh
        inPoint - A point that lies within the regional area
        points - A list of points that define the boundary of the desired
                 region as flatten list of lat, lon coordinates. i.e:

                 [lat0, lon0, lat1, lon1, lat2, lon2, ..., latN, lonN]
        """
        if self._DEBUG_ > 0:
            print("DEBUG: Marking the boundary points: ")

        boundaryCells = []

        # Find the nearest cells to the list of given boundary points
        for i in range(0, len(points), 2):
            boundaryCells.append(mesh.nearest_cell(points[i],
                                                   points[i + 1]))



        if self._DEBUG_ > 0:
            print("DEBUG: Num Boundary Cells: ", len(boundaryCells))

        # Mark the boundary cells that were given as input
        for bCells in boundaryCells:
            bdyMaskCell[bCells] = self.INSIDE

        # For each boundaryCells, mark the current cell as the source cell
        # and the next (or the first element if the current is the last) as 
        # the target cell.
        #
        # Then, determine the great-arc angle between the source and taget
        # cell, and then for each cell, starting at the source cell, 
        # calculate the great-arc angle between the cells on the current
        # cell and the target cell, and then add the cell with the smallest
        # angle.
        for i in range(len(boundaryCells)):
            sourceCell = boundaryCells[i]
            targetCell = boundaryCells[(i + 1) % len(boundaryCells)]

            # If we are already at the next target cell, there is no need
            # to connect sourceCell with targetCell, and we can skip to
            # the next pair of boundary points
            if sourceCell == targetCell:
                continue

            pta = latlon_to_xyz(mesh.latCells[sourceCell],
                                mesh.lonCells[sourceCell],
                                1.0)
            ptb = latlon_to_xyz(mesh.latCells[targetCell],
                                mesh.lonCells[targetCell],
                                1.0)
        
            pta = np.cross(pta, ptb)
            temp = np.linalg.norm(pta)
            pta = pta / temp
            iCell = sourceCell
            while iCell != targetCell:
                bdyMaskCell[iCell] = self.INSIDE
                minangle = np.Infinity
                mindist = sphere_distance(mesh.latCells[iCell],
                                          mesh.lonCells[iCell],
                                          mesh.latCells[targetCell],
                                          mesh.lonCells[targetCell],
                                          1.0)
                for j in range(mesh.nEdgesOnCell[iCell]):
                    v = mesh.cellsOnCell[iCell, j] - 1
                    dist = sphere_distance(mesh.latCells[v],
                                           mesh.lonCells[v],
                                           mesh.latCells[targetCell],
                                           mesh.lonCells[targetCell],
                                           1.0)
                    if dist > mindist:
                        continue
                    pt = latlon_to_xyz(mesh.latCells[v], mesh.lonCells[v], 1.0)
                    angle = np.dot(pta, pt)
                    angle = abs(0.5 * np.pi - np.arccos(angle))
                    if angle < minangle:
                        minangle = angle
                        k = v
                iCell = k

        return bdyMaskCell

